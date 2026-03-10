-- PROD DB assert checks for MASTER_TZ rollout
-- Fails fast with ERROR if required schema elements are missing.
-- Usage:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f docs/PROD_DB_ASSERT.sql

DO $$
BEGIN
  IF to_regclass('public.daily_mixes') IS NULL THEN
    RAISE EXCEPTION 'Missing table: public.daily_mixes';
  END IF;
  IF to_regclass('public.daily_mix_tracks') IS NULL THEN
    RAISE EXCEPTION 'Missing table: public.daily_mix_tracks';
  END IF;
  IF to_regclass('public.share_links') IS NULL THEN
    RAISE EXCEPTION 'Missing table: public.share_links';
  END IF;
  IF to_regclass('public.artist_watchlist') IS NULL THEN
    RAISE EXCEPTION 'Missing table: public.artist_watchlist';
  END IF;
  IF to_regclass('public.release_notifications') IS NULL THEN
    RAISE EXCEPTION 'Missing table: public.release_notifications';
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'release_notifications' AND column_name = 'opened_at'
  ) THEN
    RAISE EXCEPTION 'Missing column: release_notifications.opened_at';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'release_radar_enabled'
  ) THEN
    RAISE EXCEPTION 'Missing column: users.release_radar_enabled';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'fav_artists'
  ) THEN
    RAISE EXCEPTION 'Missing column: users.fav_artists';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'badges'
  ) THEN
    RAISE EXCEPTION 'Missing column: users.badges';
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'uq_daily_mix_user_date'
  ) THEN
    RAISE EXCEPTION 'Missing constraint: uq_daily_mix_user_date';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'uq_daily_mix_track'
  ) THEN
    RAISE EXCEPTION 'Missing constraint: uq_daily_mix_track';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes
    WHERE schemaname = 'public' AND tablename = 'daily_mix_tracks' AND indexname = 'ix_daily_mix_tracks_mix_pos'
  ) THEN
    RAISE EXCEPTION 'Missing index: ix_daily_mix_tracks_mix_pos';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes
    WHERE schemaname = 'public' AND tablename = 'share_links' AND indexname = 'ix_share_links_short_code'
  ) THEN
    RAISE EXCEPTION 'Missing index: ix_share_links_short_code';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'uq_artist_watchlist_user_artist'
  ) THEN
    RAISE EXCEPTION 'Missing constraint: uq_artist_watchlist_user_artist';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'uq_release_user_track'
  ) THEN
    RAISE EXCEPTION 'Missing constraint: uq_release_user_track';
  END IF;
END $$;

\echo 'OK: PROD_DB_ASSERT passed'