/**
 * Edge Function: recommend
 *
 * GET /recommend?user_id=123&limit=20
 *
 * Returns hybrid AI recommendations for a user.
 * Uses the PostgreSQL recommend_tracks() function which performs:
 *   - pgvector cosine similarity (user taste → track embeddings)
 *   - Popularity scoring
 *   - Freshness decay
 *   - Genre matching
 *   - Time-of-day boost
 *   - Artist diversity filter
 *
 * Falls back to popular tracks if user has no profile/history.
 */

import { serve } from "https://deno.land/std@0.177.0/http/server.ts";
import { corsHeaders, corsResponse } from "../_shared/cors.ts";
import { getSupabase } from "../_shared/supabase.ts";

serve(async (req: Request) => {
  if (req.method === "OPTIONS") return corsResponse();

  try {
    const url = new URL(req.url);
    const userId = parseInt(url.searchParams.get("user_id") || "0");
    const limit = Math.min(parseInt(url.searchParams.get("limit") || "20"), 50);
    const logAb = url.searchParams.get("log_ab") === "1";

    if (!userId) {
      return new Response(
        JSON.stringify({ error: "user_id required" }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } },
      );
    }

    const sb = getSupabase();

    // Call the SQL scoring function
    const { data: recs, error } = await sb.rpc("recommend_tracks", {
      p_user_id: userId,
      p_limit: limit,
    });

    if (error) throw error;

    // Format response
    const tracks = (recs || []).map((r: any) => ({
      track_id: r.track_id,
      source_id: r.source_id,
      video_id: r.source_id, // backward compat with bot
      title: r.title,
      artist: r.artist,
      genre: r.genre,
      duration: r.duration,
      cover_url: r.cover_url,
      downloads: r.downloads,
      score: r.final_score,
      algo: r.algo,
      components: {
        embed: r.s_embed,
        pop: r.s_pop,
        fresh: r.s_fresh,
        genre: r.s_genre,
        time: r.s_time,
      },
    }));

    // Log for A/B testing if requested
    if (logAb && tracks.length > 0) {
      const logs = tracks.map((t: any, i: number) => ({
        user_id: userId,
        track_id: t.track_id,
        algo: t.algo,
        position: i,
        score: t.score,
      }));

      // Fire and forget — don't block response
      sb.from("recommendation_log").insert(logs).then(() => {});
    }

    return new Response(
      JSON.stringify({ recommendations: tracks, count: tracks.length }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  } catch (err) {
    console.error("recommend error:", err);
    return new Response(
      JSON.stringify({ error: "Internal error", detail: String(err) }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  }
});
