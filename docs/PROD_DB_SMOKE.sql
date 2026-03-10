-- PROD DB smoke checks for MASTER_TZ rollout
-- Usage:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f docs/PROD_DB_SMOKE.sql

\echo '=== 1) Required tables ==='
SELECT to_regclass('public.daily_mixes')            AS daily_mixes;
SELECT to_regclass('public.daily_mix_tracks')       AS daily_mix_tracks;
SELECT to_regclass('public.share_links')            AS share_links;
SELECT to_regclass('public.artist_watchlist')       AS artist_watchlist;
SELECT to_regclass('public.release_notifications')  AS release_notifications;

\echo '=== 2) Required columns ==='
SELECT EXISTS (
  SELECT 1 FROM information_schema.columns
  WHERE table_schema = 'public' AND table_name = 'release_notifications' AND column_name = 'opened_at'
) AS has_release_notifications_opened_at;

SELECT EXISTS (
  SELECT 1 FROM information_schema.columns
  WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'release_radar_enabled'
) AS has_users_release_radar_enabled;

SELECT EXISTS (
  SELECT 1 FROM information_schema.columns
  WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'fav_artists'
) AS has_users_fav_artists;

SELECT EXISTS (
  SELECT 1 FROM information_schema.columns
  WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'badges'
) AS has_users_badges;

\echo '=== 3) Constraints / indexes (critical) ==='
-- Daily Mix unique per user/day
SELECT conname, contype
FROM pg_constraint
WHERE conname = 'uq_daily_mix_user_date';

-- Daily Mix Track unique and order index
SELECT conname, contype
FROM pg_constraint
WHERE conname = 'uq_daily_mix_track';

SELECT indexname
FROM pg_indexes
WHERE schemaname = 'public' AND tablename = 'daily_mix_tracks' AND indexname = 'ix_daily_mix_tracks_mix_pos';

-- Share links uniqueness
SELECT indexname
FROM pg_indexes
WHERE schemaname = 'public' AND tablename = 'share_links' AND indexname = 'ix_share_links_short_code';

-- Artist watchlist unique user+artist
SELECT conname, contype
FROM pg_constraint
WHERE conname = 'uq_artist_watchlist_user_artist';

-- Release notifications unique user+track
SELECT conname, contype
FROM pg_constraint
WHERE conname = 'uq_release_user_track';

\echo '=== 4) Basic row-count sanity (informational) ==='
SELECT 'daily_mixes' AS table_name, COUNT(*) AS rows_count FROM daily_mixes
UNION ALL
SELECT 'daily_mix_tracks', COUNT(*) FROM daily_mix_tracks
UNION ALL
SELECT 'share_links', COUNT(*) FROM share_links
UNION ALL
SELECT 'artist_watchlist', COUNT(*) FROM artist_watchlist
UNION ALL
SELECT 'release_notifications', COUNT(*) FROM release_notifications;