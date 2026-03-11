/**
 * Edge Function: similar
 *
 * GET /similar?track_id=123&limit=10
 * GET /similar?source_id=yt_xxx&limit=10
 *
 * Returns tracks similar to a given track using pgvector embedding similarity.
 */

import { serve } from "https://deno.land/std@0.177.0/http/server.ts";
import { corsHeaders, corsResponse } from "../_shared/cors.ts";
import { getSupabase } from "../_shared/supabase.ts";

serve(async (req: Request) => {
  if (req.method === "OPTIONS") return corsResponse();

  try {
    const url = new URL(req.url);
    let trackId = parseInt(url.searchParams.get("track_id") || "0");
    const sourceId = url.searchParams.get("source_id") || "";
    const limit = Math.min(parseInt(url.searchParams.get("limit") || "10"), 50);

    const sb = getSupabase();

    // Resolve source_id → track_id
    if (!trackId && sourceId) {
      const { data } = await sb
        .from("tracks")
        .select("id")
        .eq("source_id", sourceId)
        .single();
      trackId = data?.id || 0;
    }

    if (!trackId) {
      return new Response(
        JSON.stringify({ error: "track_id or source_id required" }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } },
      );
    }

    const { data: tracks, error } = await sb.rpc("similar_tracks", {
      p_track_id: trackId,
      p_limit: limit,
    });

    if (error) throw error;

    const result = (tracks || []).map((t: any) => ({
      track_id: t.track_id,
      source_id: t.source_id,
      video_id: t.source_id,
      title: t.title,
      artist: t.artist,
      genre: t.genre,
      similarity: t.similarity,
    }));

    return new Response(
      JSON.stringify({ similar: result, count: result.length }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  } catch (err) {
    console.error("similar error:", err);
    return new Response(
      JSON.stringify({ error: "Internal error", detail: String(err) }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  }
});
