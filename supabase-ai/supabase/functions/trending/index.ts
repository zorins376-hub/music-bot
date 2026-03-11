/**
 * Edge Function: trending
 *
 * GET /trending?hours=24&limit=20&genre=pop
 *
 * Returns currently trending tracks based on play velocity.
 * Compares current period vs previous period to detect rising/falling/hot tracks.
 */

import { serve } from "https://deno.land/std@0.177.0/http/server.ts";
import { corsHeaders, corsResponse } from "../_shared/cors.ts";
import { getSupabase } from "../_shared/supabase.ts";

serve(async (req: Request) => {
  if (req.method === "OPTIONS") return corsResponse();

  try {
    const url = new URL(req.url);
    const hours = Math.min(Math.max(parseInt(url.searchParams.get("hours") || "24"), 1), 168);
    const limit = Math.min(Math.max(parseInt(url.searchParams.get("limit") || "20"), 1), 50);
    const genre = url.searchParams.get("genre") || null;

    const sb = getSupabase();

    const { data: tracks, error } = await sb.rpc("trending_tracks", {
      p_hours: hours,
      p_limit: limit,
      p_genre: genre,
    });

    if (error) throw error;

    const result = (tracks || []).map((t: any) => ({
      track_id: t.track_id,
      source_id: t.source_id,
      video_id: t.source_id,
      title: t.title,
      artist: t.artist,
      genre: t.genre,
      duration: t.duration,
      cover_url: t.cover_url,
      play_count: t.play_count,
      unique_users: t.unique_users,
      velocity: t.velocity,
      trend: t.trend,
    }));

    return new Response(
      JSON.stringify({
        trending: result,
        count: result.length,
        window_hours: hours,
        genre: genre,
      }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  } catch (err) {
    console.error("trending error:", err);
    return new Response(
      JSON.stringify({ error: "Internal error", detail: String(err) }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  }
});
