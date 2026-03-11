/**
 * Edge Function: ingest
 *
 * POST /ingest
 * Body: { "event": "play"|"skip"|"like"|"dislike",
 *         "user_id": 123,
 *         "track": { "source_id": "yt_xxx", "title": "...", "artist": "...", ... },
 *         "listen_duration": 180,
 *         "source": "search" }
 *
 * Ingests listening events:
 *   1. Upsert track in tracks table
 *   2. Insert into listening_history
 *   3. If play count % 10 == 0 → trigger profile update
 *   4. Queue track for embedding if no embedding exists
 */

import { serve } from "https://deno.land/std@0.177.0/http/server.ts";
import { corsHeaders, corsResponse } from "../_shared/cors.ts";
import { getSupabase } from "../_shared/supabase.ts";

interface IngestEvent {
  event: "play" | "skip" | "like" | "dislike";
  user_id: number;
  track: {
    source_id: string;
    title?: string;
    artist?: string;
    genre?: string;
    bpm?: number;
    duration?: number;
    file_id?: string;
    cover_url?: string;
    source?: string;
    channel?: string;
  };
  listen_duration?: number;
  source?: string;
  query?: string;
}

serve(async (req: Request) => {
  if (req.method === "OPTIONS") return corsResponse();

  try {
    const body: IngestEvent = await req.json();
    const { event, user_id, track, listen_duration, source, query } = body;

    if (!user_id || !track?.source_id || !event) {
      return new Response(
        JSON.stringify({ error: "user_id, track.source_id, and event required" }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } },
      );
    }

    const sb = getSupabase();

    // ── 1. Upsert user ──────────────────────────────────────────────────
    await sb.from("users").upsert(
      { id: user_id, last_active: new Date().toISOString() },
      { onConflict: "id", ignoreDuplicates: false },
    );

    // ── 2. Upsert track ─────────────────────────────────────────────────
    const trackData: Record<string, unknown> = {
      source_id: track.source_id,
      source: track.source || "youtube",
    };
    if (track.title) trackData.title = track.title;
    if (track.artist) trackData.artist = track.artist;
    if (track.genre) trackData.genre = track.genre;
    if (track.bpm) trackData.bpm = track.bpm;
    if (track.duration) trackData.duration = track.duration;
    if (track.file_id) trackData.file_id = track.file_id;
    if (track.cover_url) trackData.cover_url = track.cover_url;
    if (track.channel) trackData.channel = track.channel;

    // Increment downloads on play
    if (event === "play") {
      trackData.downloads = 1; // Will be handled by upsert logic below
    }

    const { data: upsertedTrack } = await sb
      .from("tracks")
      .upsert(trackData, { onConflict: "source_id" })
      .select("id, embedding")
      .single();

    const trackId = upsertedTrack?.id;

    // Increment downloads counter separately (atomic)
    if (event === "play" && trackId) {
      await sb.rpc("increment_downloads", { p_track_id: trackId });
    }

    // ── 3. Insert listening history ─────────────────────────────────────
    if (trackId) {
      await sb.from("listening_history").insert({
        user_id,
        track_id: trackId,
        action: event,
        listen_duration: listen_duration || null,
        source: source || "search",
        query: query || null,
      });
    }

    // ── 4. Queue for embedding if missing ───────────────────────────────
    if (trackId && !upsertedTrack?.embedding && track.title) {
      await sb.from("embedding_queue").upsert(
        { track_id: trackId },
        { onConflict: "track_id", ignoreDuplicates: true },
      );
    }

    // ── 5. Update profile every 10 plays ────────────────────────────────
    if (event === "play") {
      const { count } = await sb
        .from("listening_history")
        .select("*", { count: "exact", head: true })
        .eq("user_id", user_id)
        .eq("action", "play");

      if (count && count % 10 === 0) {
        // Trigger profile update (fire and forget)
        sb.rpc("update_user_profile", { p_user_id: user_id }).then(() => {});
      }
    }

    return new Response(
      JSON.stringify({ ok: true, track_id: trackId }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  } catch (err) {
    console.error("ingest error:", err);
    return new Response(
      JSON.stringify({ error: "Internal error", detail: String(err) }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  }
});
