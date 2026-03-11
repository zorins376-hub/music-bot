/**
 * Edge Function: ai-playlist
 *
 * POST /ai-playlist
 * Body: { "user_id": 123, "prompt": "грустный плейлист на вечер", "limit": 10 }
 *
 * Uses Google Gemini to understand the prompt, then:
 *   1. Extracts mood/genre/artist/era from the prompt via Gemini Flash
 *   2. Searches track embeddings via pgvector for matching tracks
 *   3. Falls back to keyword-based SQL search
 *   4. Returns a curated playlist
 */

import { serve } from "https://deno.land/std@0.177.0/http/server.ts";
import { corsHeaders, corsResponse } from "../_shared/cors.ts";
import { getSupabase } from "../_shared/supabase.ts";

const GEMINI_API_KEY = Deno.env.get("GEMINI_API_KEY") || "";
const EMBED_MODEL = "gemini-embedding-001";
const EMBED_URL = `https://generativelanguage.googleapis.com/v1beta/models/${EMBED_MODEL}`;
const CHAT_MODEL = "gemini-2.0-flash";
const CHAT_URL = `https://generativelanguage.googleapis.com/v1beta/models/${CHAT_MODEL}`;

interface PlaylistRequest {
  user_id: number;
  prompt: string;
  limit?: number;
}

serve(async (req: Request) => {
  if (req.method === "OPTIONS") return corsResponse();

  try {
    const body: PlaylistRequest = await req.json();
    const { user_id, prompt, limit = 10 } = body;

    if (!prompt) {
      return new Response(
        JSON.stringify({ error: "prompt required" }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } },
      );
    }

    const sb = getSupabase();
    let tracks: any[] = [];

    // ── Strategy 1: Gemini embedding search ──────────────────────────────
    if (GEMINI_API_KEY) {
      tracks = await embeddingSearch(sb, prompt, limit);
    }

    // ── Strategy 2: Gemini-powered keyword search ───────────────────────
    if (tracks.length < limit && GEMINI_API_KEY) {
      const keywords = await extractKeywords(prompt);
      const moreTracks = await keywordSearch(sb, keywords, limit - tracks.length);
      const seenIds = new Set(tracks.map((t) => t.id));
      for (const t of moreTracks) {
        if (!seenIds.has(t.id)) {
          tracks.push(t);
          seenIds.add(t.id);
        }
      }
    }

    // ── Strategy 3: Simple SQL keyword fallback ─────────────────────────
    if (tracks.length < 3) {
      const words = prompt.toLowerCase().split(/\s+/).filter((w) => w.length > 2);
      const fallback = await keywordSearch(sb, words, limit);
      const seenIds = new Set(tracks.map((t) => t.id));
      for (const t of fallback) {
        if (!seenIds.has(t.id)) {
          tracks.push(t);
          seenIds.add(t.id);
        }
      }
    }

    const playlist = tracks.slice(0, limit).map((t: any, i: number) => ({
      position: i,
      track_id: t.id,
      source_id: t.source_id,
      video_id: t.source_id,
      title: t.title,
      artist: t.artist,
      genre: t.genre,
      duration: t.duration,
      cover_url: t.cover_url,
    }));

    return new Response(
      JSON.stringify({
        playlist,
        count: playlist.length,
        prompt,
        method: GEMINI_API_KEY ? "ai" : "keyword",
      }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  } catch (err) {
    console.error("ai-playlist error:", err);
    return new Response(
      JSON.stringify({ error: "Internal error", detail: String(err) }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  }
});

/**
 * Embed the prompt text with Gemini, then find closest tracks via pgvector.
 */
async function embeddingSearch(sb: any, prompt: string, limit: number) {
  const url = `${EMBED_URL}:embedContent?key=${GEMINI_API_KEY}`;
  const embResp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: `models/${EMBED_MODEL}`,
      content: { parts: [{ text: prompt }] },
      taskType: "RETRIEVAL_QUERY",
      outputDimensionality: 768,
    }),
  });

  if (!embResp.ok) return [];

  const embData = await embResp.json();
  const embedding = embData.embedding?.values;
  if (!embedding) return [];

  const { data, error } = await sb.rpc("match_tracks_by_embedding", {
    query_embedding: embedding,
    match_threshold: 0.3,
    match_count: limit,
  });

  return data || [];
}

/**
 * Use Gemini Flash to extract search keywords from a natural language prompt.
 */
async function extractKeywords(prompt: string): Promise<string[]> {
  const url = `${CHAT_URL}:generateContent?key=${GEMINI_API_KEY}`;
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      contents: [{
        parts: [{
          text: `Extract music search keywords from this user prompt. Return a JSON array of 3-6 search terms (artist names, genres, moods). Return ONLY the JSON array, no other text.\n\nPrompt: "${prompt}"`,
        }],
      }],
      generationConfig: {
        temperature: 0.5,
        maxOutputTokens: 150,
      },
    }),
  });

  if (!resp.ok) return [];

  const data = await resp.json();
  const text = data.candidates?.[0]?.content?.parts?.[0]?.text?.trim() || "[]";
  try {
    // Strip markdown code blocks if present
    const cleaned = text.replace(/```json\n?/g, "").replace(/```\n?/g, "").trim();
    return JSON.parse(cleaned);
  } catch {
    return [prompt];
  }
}

/**
 * Search tracks by keywords in title/artist/genre.
 */
async function keywordSearch(sb: any, keywords: string[], limit: number) {
  if (keywords.length === 0) return [];

  // Build OR conditions for each keyword
  const conditions = keywords.map((kw) =>
    `title.ilike.%${kw}%,artist.ilike.%${kw}%,genre.ilike.%${kw}%`
  );

  const { data, error } = await sb
    .from("tracks")
    .select("id, source_id, title, artist, genre, duration, cover_url")
    .or(conditions.join(","))
    .not("file_id", "is", null)
    .order("downloads", { ascending: false })
    .limit(limit);

  return data || [];
}
