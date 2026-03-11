-- ═══════════════════════════════════════════════════════════════════════════════
-- Migration 004: Scheduled jobs via pg_cron
-- ═══════════════════════════════════════════════════════════════════════════════

-- Recalculate profiles for active users every 4 hours
select extensions.cron_schedule(
    'update-active-profiles',
    '0 */4 * * *',  -- every 4 hours
    $$
    select update_user_profile(u.id)
    from users u
    where u.last_active > now() - interval '7 days';
    $$
);

-- Trigger embedding generation for tracks without embeddings (every 10 min)
-- This calls the Edge Function via pg_net
select extensions.cron_schedule(
    'embed-new-tracks',
    '*/10 * * * *',  -- every 10 minutes
    $$
    select extensions.http_post(
        url := current_setting('app.supabase_url') || '/functions/v1/embed-tracks',
        headers := jsonb_build_object(
            'Authorization', 'Bearer ' || current_setting('app.service_role_key'),
            'Content-Type', 'application/json'
        ),
        body := '{"batch_size": 50}'::jsonb
    );
    $$
);

-- Clean old recommendation logs (older than 30 days)
select extensions.cron_schedule(
    'cleanup-reclog',
    '0 3 * * *',  -- daily at 3 AM UTC
    $$
    delete from recommendation_log
    where created_at < now() - interval '30 days';
    $$
);
