/**
 * Edge Function: feedback
 *
 * POST /feedback
 * Body: { user_id, track_id?, source_id?, feedback, context? }
 *
 * Records explicit user feedback (like/dislike/skip/save/share/repeat).
 * Updates recommendation_log if track was shown via recommendations.
 * Triggers profile recalculation every 5th feedback event.
 */

import { serve } from "https://deno.land/std@0.177.0/http/server.ts";
import { corsHeaders, corsResponse } from "../_shared/cors.ts";
import { getSupabase } from "../_shared/supabase.ts";

const VALID_FEEDBACK = ["like", "dislike", "skip", "save", "share", "repeat"];

serve(async (req: Request) => {
  if (req.method === "OPTIONS") return corsResponse();

  try {
    const body = await req.json();
    const { user_id, source_id, feedback, context } = body;
    let track_id = body.track_id;

    if (!user_id || !feedback) {
      return new Response(
        JSON.stringify({ error: "user_id and feedback are required" }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } },
      );
    }

    if (!VALID_FEEDBACK.includes(feedback)) {
      return new Response(
        JSON.stringify({ error: `Invalid feedback. Must be one of: ${VALID_FEEDBACK.join(", ")}` }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } },
      );
    }

    const sb = getSupabase();

    // Resolve source_id → track_id if needed
    if (!track_id && source_id) {
      const { data } = await sb
        .from("tracks")
        .select("id")
        .eq("source_id", source_id)
        .single();
      track_id = data?.id || null;
    }

    // Insert feedback
    const { error: fbErr } = await sb
      .from("user_feedback")
      .insert({
        user_id,
        track_id,
        source_id: source_id || null,
        feedback,
        context: context || null,
      });

    if (fbErr) throw fbErr;

    // Also mirror to listening_history for profile computation
    if (track_id && (feedback === "like" || feedback === "dislike" || feedback === "skip")) {
      await sb.from("listening_history").insert({
        user_id,
        track_id,
        action: feedback,
        source: context || "feedback",
      });
    }

    // Mark as clicked in recommendation_log if from recommendations
    if (context === "recommend" && track_id && (feedback === "like" || feedback === "save")) {
      await sb
        .from("recommendation_log")
        .update({ clicked: true })
        .eq("user_id", user_id)
        .eq("track_id", track_id)
        .eq("clicked", false);
    }

    // Trigger profile update every 5th feedback
    const { count } = await sb
      .from("user_feedback")
      .select("id", { count: "exact", head: true })
      .eq("user_id", user_id);

    if (count && count % 5 === 0) {
      sb.rpc("update_user_profile", { p_user_id: user_id }).then(() => {});
    }

    return new Response(
      JSON.stringify({ ok: true, feedback, track_id }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  } catch (err) {
    console.error("feedback error:", err);
    return new Response(
      JSON.stringify({ error: "Internal error", detail: String(err) }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  }
});
