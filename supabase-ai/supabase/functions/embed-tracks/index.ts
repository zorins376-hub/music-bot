/**
 * Edge Function: embed-tracks
 *
 * POST /embed-tracks
 * Body: { "batch_size": 50 }
 *
 * Processes tracks from the embedding_queue:
 *   1. Fetches batch of tracks without embeddings
 *   2. Generates embeddings via OpenAI text-embedding-3-small
 *   3. Stores embeddings in tracks.embedding (pgvector)
 *   4. Removes processed tracks from queue
 *
 * Called by pg_cron every 10 minutes, or manually.
 */

import { serve } from "https://deno.land/std@0.177.0/http/server.ts";
import { corsHeaders, corsResponse } from "../_shared/cors.ts";
import { getSupabase } from "../_shared/supabase.ts";

const OPENAI_API_KEY = Deno.env.get("OPENAI_API_KEY") || "";
const MAX_RETRIES = 3;

serve(async (req: Request) => {
  if (req.method === "OPTIONS") return corsResponse();

  try {
    const body = await req.json().catch(() => ({}));
    const batchSize = Math.min(body.batch_size || 50, 100);

    if (!OPENAI_API_KEY) {
      return new Response(
        JSON.stringify({ error: "OPENAI_API_KEY not configured" }),
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
    // Format: "Artist - Title [genre]" for rich semantic representation
    const texts = tracks.map((t: any) => {
      const parts: string[] = [];
      if (t.artist) parts.push(t.artist);
      if (t.title) parts.push(t.title);
      const text = parts.join(" - ") || `Track ${t.id}`;
      return t.genre ? `${text} [${t.genre}]` : text;
    });

    // ── 4. Call OpenAI Embeddings API ───────────────────────────────────
    const embResp = await fetch("https://api.openai.com/v1/embeddings", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${OPENAI_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: "text-embedding-3-small",
        input: texts,
      }),
    });

    if (!embResp.ok) {
      const errText = await embResp.text();
      // Increment attempt counters
      for (const tid of trackIds) {
        await sb
          .from("embedding_queue")
          .update({ attempts: (queue.find((q: any) => q.track_id === tid)?.attempts || 0) + 1, last_error: errText })
          .eq("track_id", tid);
      }
      throw new Error(`OpenAI API error: ${embResp.status} ${errText}`);
    }

    const embData = await embResp.json();
    const embeddings = embData.data as Array<{ index: number; embedding: number[] }>;

    // ── 5. Store embeddings in tracks table ─────────────────────────────
    let processed = 0;
    const errors: string[] = [];

    for (const emb of embeddings) {
      const track = tracks[emb.index];
      if (!track) continue;

      const { error: uErr } = await sb
        .from("tracks")
        .update({ embedding: emb.embedding })
        .eq("id", track.id);

      if (uErr) {
        errors.push(`Track ${track.id}: ${uErr.message}`);
        continue;
      }

      // Remove from queue
      await sb.from("embedding_queue").delete().eq("track_id", track.id);
      processed++;
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
