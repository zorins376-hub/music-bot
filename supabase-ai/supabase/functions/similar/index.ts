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

    let result = (tracks || []).map((t: any) => ({
      track_id: t.track_id,
      source_id: t.source_id,
      video_id: t.source_id,
      title: t.title,
      artist: t.artist,
      genre: t.genre,
      similarity: t.similarity,
    }));

    // Fallback: if vector similarity returned too few, fill with same genre/artist
    if (result.length < limit) {
      const remaining = limit - result.length;
      const excludeIds = [trackId, ...result.map((r: any) => r.track_id)];

      // Get the source track's genre and artist
      const { data: srcTrack } = await sb
        .from("tracks")
        .select("genre, artist")
        .eq("id", trackId)
        .single();

      if (srcTrack) {
        const filters: string[] = [];
        if (srcTrack.genre) filters.push(`genre.eq.${srcTrack.genre}`);
        if (srcTrack.artist) filters.push(`artist.eq.${srcTrack.artist}`);

        if (filters.length > 0) {
          const { data: fallback } = await sb
            .from("tracks")
            .select("id, source_id, title, artist, genre")
            .or(filters.join(","))
            .not("id", "in", `(${excludeIds.join(",")})`)
            .not("file_id", "is", null)
            .order("downloads", { ascending: false })
            .limit(remaining);

          if (fallback) {
            result = result.concat(
              fallback.map((t: any) => ({
                track_id: t.id,
                source_id: t.source_id,
                video_id: t.source_id,
                title: t.title,
                artist: t.artist,
                genre: t.genre,
                similarity: 0,
              })),
            );
          }
        }
      }
    }

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
