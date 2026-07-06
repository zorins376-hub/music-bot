-- ═══════════════════════════════════════════════════════════════════════════════
-- Migration 007: Fix embed-new-tracks cron job to use inline URL/key
--
-- The previous cron job used current_setting('app.supabase_url') which
-- requires ALTER DATABASE (superuser). Instead, we inline the values.
-- ═══════════════════════════════════════════════════════════════════════════════

-- Drop the old cron job that depends on app settings
select cron.unschedule('embed-new-tracks');

-- Recreate with inline values
select cron.schedule(
    'embed-new-tracks',
    '*/10 * * * *',
    $$
    select net.http_post(
        url := 'https://vexyurbyobnpzyatiikw.supabase.co/functions/v1/embed-tracks',
        headers := jsonb_build_object(
            -- SECURITY: the service_role JWT that was inlined here leaked in a PUBLIC
            -- repo and MUST be rotated in the Supabase dashboard. Do NOT inline keys;
            -- read from Supabase Vault instead, e.g.:
            --   'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name = 'service_role_key')
            'Authorization', 'Bearer <ROTATED_SERVICE_ROLE_KEY__READ_FROM_VAULT>',
            'Content-Type', 'application/json'
        ),
        body := '{"batch_size": 50}'::jsonb
    );
    $$
);
