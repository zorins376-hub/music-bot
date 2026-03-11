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
            'Authorization', 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZleHl1cmJ5b2JucHp5YXRpaWt3Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MzE3OTkzOCwiZXhwIjoyMDg4NzU1OTM4fQ.qa9t7XPT2XkYYz21yHg8vS_ZQLGWxNStJWRjuNWnU9U',
            'Content-Type', 'application/json'
        ),
        body := '{"batch_size": 50}'::jsonb
    );
    $$
);
