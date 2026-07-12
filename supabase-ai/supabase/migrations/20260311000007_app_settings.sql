-- ═══════════════════════════════════════════════════════════════════════════════
-- Migration 007: Fix embed-new-tracks cron job to use inline URL/key
--
-- The previous cron job used current_setting('app.supabase_url') which
-- requires ALTER DATABASE (superuser). Instead, we inline the values.
-- ═══════════════════════════════════════════════════════════════════════════════

-- Drop the old cron job that depends on app settings
select cron.unschedule('embed-new-tracks');

-- Recreate reading the service_role key from Supabase Vault instead of
-- inlining it. Store it once with:
--   select vault.create_secret('<service_role_key>', 'service_role_key');
select cron.schedule(
    'embed-new-tracks',
    '*/10 * * * *',
    $$
    select net.http_post(
        url := 'https://vexyurbyobnpzyatiikw.supabase.co/functions/v1/embed-tracks',
        headers := jsonb_build_object(
            'Authorization', 'Bearer ' || (
                select decrypted_secret from vault.decrypted_secrets
                where name = 'service_role_key' limit 1
            ),
            'Content-Type', 'application/json'
        ),
        body := '{"batch_size": 50}'::jsonb
    );
    $$
);
