/**
 * Edge Function: analytics
 *
 * GET /analytics?days=7
 *
 * Returns AI system analytics:
 *   - A/B test report (CTR by algo)
 *   - Embedding coverage stats
 *   - Top recommended tracks
 *   - User profile coverage
 */

import { serve } from "https://deno.land/std@0.177.0/http/server.ts";
import { corsHeaders, corsResponse } from "../_shared/cors.ts";
import { getSupabase } from "../_shared/supabase.ts";

serve(async (req: Request) => {
  if (req.method === "OPTIONS") return corsResponse();

  try {
    const url = new URL(req.url);
    const days = parseInt(url.searchParams.get("days") || "7");

    const sb = getSupabase();

    // A/B test report
    const { data: abReport } = await sb.rpc("ab_test_report", {
      p_days: days,
    });

    // Embedding coverage
    const { count: totalTracks } = await sb
      .from("tracks")
      .select("*", { count: "exact", head: true });

    const { count: embeddedTracks } = await sb
      .from("tracks")
      .select("*", { count: "exact", head: true })
      .not("embedding", "is", null);

    const { count: queueSize } = await sb
      .from("embedding_queue")
      .select("*", { count: "exact", head: true });

    // Profile coverage
    const { count: totalUsers } = await sb
      .from("users")
      .select("*", { count: "exact", head: true });

    const { count: profiledUsers } = await sb
      .from("user_profiles")
      .select("*", { count: "exact", head: true })
      .not("taste_embedding", "is", null);

    // Listening stats
    const { count: totalPlays } = await sb
      .from("listening_history")
      .select("*", { count: "exact", head: true })
      .eq("action", "play");

    return new Response(
      JSON.stringify({
        ab_test: abReport || [],
        embeddings: {
          total_tracks: totalTracks || 0,
          embedded_tracks: embeddedTracks || 0,
          coverage_pct: totalTracks
            ? Math.round(((embeddedTracks || 0) / totalTracks) * 100)
            : 0,
          queue_size: queueSize || 0,
        },
        profiles: {
          total_users: totalUsers || 0,
          profiled_users: profiledUsers || 0,
          coverage_pct: totalUsers
            ? Math.round(((profiledUsers || 0) / totalUsers) * 100)
            : 0,
        },
        total_plays: totalPlays || 0,
        period_days: days,
      }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  } catch (err) {
    console.error("analytics error:", err);
    return new Response(
      JSON.stringify({ error: "Internal error", detail: String(err) }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  }
});
