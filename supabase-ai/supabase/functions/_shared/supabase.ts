/** Shared Supabase client for Edge Functions (service_role) */

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

export function getSupabase() {
  return createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  );
}
