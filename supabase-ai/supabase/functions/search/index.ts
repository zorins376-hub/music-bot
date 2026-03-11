/**
 * Edge Function: search
 *
 * GET /search?q=metallica&limit=20&genre=metal
 *
 * Full-text search across the Supabase tracks catalog
 * using PostgreSQL tsvector with ranking.
 */

import { serve } from "https://deno.land/std@0.177.0/http/server.ts";
import { corsHeaders, corsResponse } from "../_shared/cors.ts";
import { getSupabase } from "../_shared/supabase.ts";

serve(async (req: Request) => {
  if (req.method === "OPTIONS") return corsResponse();

  try {
    const url = new URL(req.url);
    const query = (url.searchParams.get("q") || "").trim();
    const limit = Math.min(Math.max(parseInt(url.searchParams.get("limit") || "20"), 1), 50);
    const genre = url.searchParams.get("genre") || null;

    if (!query) {
      return new Response(
        JSON.stringify({ error: "q parameter is required" }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } },
      );
    }

    const sb = getSupabase();

    const { data: tracks, error } = await sb.rpc("search_tracks", {
      p_query: query,
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
      downloads: t.downloads,
      rank: t.rank,
    }));

    return new Response(
      JSON.stringify({
        results: result,
        count: result.length,
        query,
      }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  } catch (err) {
    console.error("search error:", err);
    return new Response(
      JSON.stringify({ error: "Internal error", detail: String(err) }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  }
});
