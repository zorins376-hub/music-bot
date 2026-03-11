/**
 * Edge Function: embed-tracks
 *
 * POST /embed-tracks
 * Body: { "batch_size": 50 }
 *
 * Processes tracks from the embedding_queue:
 *   1. Fetches batch of tracks without embeddings
 *   2. Generates embeddings via Google Gemini text-embedding-004 (768d, free)
 *   3. Stores embeddings in tracks.embedding (pgvector)
 *   4. Removes processed tracks from queue
 *
 * Called by pg_cron every 10 minutes, or manually.
 */

import { serve } from "https://deno.land/std@0.177.0/http/server.ts";
import { corsHeaders, corsResponse } from "../_shared/cors.ts";
import { getSupabase } from "../_shared/supabase.ts";

const GEMINI_API_KEY = Deno.env.get("GEMINI_API_KEY") || "";
const GEMINI_MODEL = "gemini-embedding-001";
const GEMINI_URL = `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}`;
const EMBED_DIMENSIONS = 768;
const MAX_RETRIES = 3;

/**
 * Get embedding for a single text via Gemini.
 */
async function getEmbedding(text: string): Promise<number[]> {
  const resp = await fetch(`${GEMINI_URL}:embedContent?key=${GEMINI_API_KEY}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: `models/${GEMINI_MODEL}`,
      content: { parts: [{ text }] },
      taskType: "RETRIEVAL_DOCUMENT",
      outputDimensionality: EMBED_DIMENSIONS,
    }),
  });
  if (!resp.ok) {
    const errText = await resp.text();
    throw new Error(`Gemini API error: ${resp.status} ${errText}`);
  }
  const data = await resp.json();
  return data.embedding?.values || [];
}

/**
 * Get embeddings for multiple texts via parallel embedContent calls.
 * Processes in chunks to respect rate limits.
 */
async function getBatchEmbeddings(texts: string[]): Promise<number[][]> {
  const PARALLEL = 5;
  const results: number[][] = [];
  for (let i = 0; i < texts.length; i += PARALLEL) {
    const chunk = texts.slice(i, i + PARALLEL);
    const chunkResults = await Promise.all(chunk.map((t) => getEmbedding(t)));
    results.push(...chunkResults);
  }
  return results;
}

serve(async (req: Request) => {
  if (req.method === "OPTIONS") return corsResponse();

  try {
    const body = await req.json().catch(() => ({}));
    const batchSize = Math.min(body.batch_size || 50, 100);

    if (!GEMINI_API_KEY) {
      return new Response(
        JSON.stringify({ error: "GEMINI_API_KEY not configured" }),
        { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } },
      );
    }

    const sb = getSupabase();

    // ── 1. Get tracks from queue ────────────────────────────────────────
    const { data: queue, error: qErr } = await sb
      .from("embedding_queue")
      .select("track_id, attempts")
      .lt("attempts", MAX_RETRIES)
      .order("created_at", { ascending: true })
      .limit(batchSize);

    if (qErr) throw qErr;
    if (!queue || queue.length === 0) {
      return new Response(
        JSON.stringify({ processed: 0, message: "Queue empty" }),
        { headers: { ...corsHeaders, "Content-Type": "application/json" } },
      );
    }

    const trackIds = queue.map((q: any) => q.track_id);

    // ── 2. Get track metadata ───────────────────────────────────────────
    const { data: tracks, error: tErr } = await sb
      .from("tracks")
      .select("id, title, artist, genre")
      .in("id", trackIds);

    if (tErr) throw tErr;
    if (!tracks || tracks.length === 0) {
      return new Response(
        JSON.stringify({ processed: 0, message: "No tracks found" }),
        { headers: { ...corsHeaders, "Content-Type": "application/json" } },
      );
    }

    // ── 3. Build text for embedding ─────────────────────────────────────
    const texts = tracks.map((t: any) => {
      const parts: string[] = [];
      if (t.artist) parts.push(t.artist);
      if (t.title) parts.push(t.title);
      const text = parts.join(" - ") || `Track ${t.id}`;
      return t.genre ? `${text} [${t.genre}]` : text;
    });

    // ── 4. Call Gemini Embeddings API (batch, max 100 per call) ─────────
    // Gemini batchEmbedContents supports up to 100 texts per request
    let allEmbeddings: number[][] = [];
    const BATCH_LIMIT = 100;
    for (let i = 0; i < texts.length; i += BATCH_LIMIT) {
      const batch = texts.slice(i, i + BATCH_LIMIT);
      try {
        const batchResult = await getBatchEmbeddings(batch);
        allEmbeddings = allEmbeddings.concat(batchResult);
      } catch (err) {
        // Increment attempt counters for failed batch
        const failedIds = tracks.slice(i, i + BATCH_LIMIT).map((t: any) => t.id);
        for (const tid of failedIds) {
          await sb
            .from("embedding_queue")
            .update({
              attempts: (queue.find((q: any) => q.track_id === tid)?.attempts || 0) + 1,
              last_error: String(err),
            })
            .eq("track_id", tid);
        }
        throw err;
      }
    }

    // ── 5. Store embeddings in tracks table (batch) ────────────────────
    let processed = 0;
    const errors: string[] = [];
    const updates: Array<{ id: number; embedding: number[] }> = [];
    const doneIds: number[] = [];

    for (let i = 0; i < allEmbeddings.length; i++) {
      const track = tracks[i];
      if (!track || !allEmbeddings[i]?.length) continue;
      updates.push({ id: track.id, embedding: allEmbeddings[i] });
    }

    const CHUNK = 10;
    for (let i = 0; i < updates.length; i += CHUNK) {
      const chunk = updates.slice(i, i + CHUNK);
      const results = await Promise.allSettled(
        chunk.map(async (u) => {
          const { error: uErr } = await sb
            .from("tracks")
            .update({ embedding: u.embedding })
            .eq("id", u.id);
          if (uErr) throw new Error(`Track ${u.id}: ${uErr.message}`);
          doneIds.push(u.id);
          return u.id;
        }),
      );
      for (const r of results) {
        if (r.status === "fulfilled") {
          processed++;
        } else {
          errors.push(r.reason?.message || "Unknown error");
        }
      }
    }

    if (doneIds.length > 0) {
      await sb.from("embedding_queue").delete().in("track_id", doneIds);
    }

    return new Response(
      JSON.stringify({
        processed,
        total_in_batch: tracks.length,
        errors: errors.length > 0 ? errors : undefined,
      }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  } catch (err) {
    console.error("embed-tracks error:", err);
    return new Response(
      JSON.stringify({ error: "Internal error", detail: String(err) }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  }
});
