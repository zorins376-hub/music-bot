/**
 * Edge Function: update-profile
 *
 * POST /update-profile
 * Body: { "user_id": 123 }
 *
 * Triggers recalculation of user AI profile.
 * Wraps the SQL function update_user_profile().
 */

import { serve } from "https://deno.land/std@0.177.0/http/server.ts";
import { corsHeaders, corsResponse } from "../_shared/cors.ts";
import { getSupabase } from "../_shared/supabase.ts";

serve(async (req: Request) => {
  if (req.method === "OPTIONS") return corsResponse();

  try {
    const body = await req.json();
    const userId = body.user_id;

    if (!userId) {
      return new Response(
        JSON.stringify({ error: "user_id required" }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } },
      );
    }

    const sb = getSupabase();

    const { error } = await sb.rpc("update_user_profile", {
      p_user_id: userId,
    });

    if (error) throw error;

    // Fetch updated profile
    const { data: profile } = await sb
      .from("user_profiles")
      .select("*")
      .eq("user_id", userId)
      .single();

    return new Response(
      JSON.stringify({ ok: true, profile }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  } catch (err) {
    console.error("update-profile error:", err);
    return new Response(
      JSON.stringify({ error: "Internal error", detail: String(err) }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  }
});
