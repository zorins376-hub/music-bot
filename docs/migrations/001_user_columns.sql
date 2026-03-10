-- Migration: Add new User columns (v1.2 - v1.5)
-- Run against production DATABASE_URL

-- AI DJ Profile (v1.2)
ALTER TABLE users ADD COLUMN IF NOT EXISTS fav_genres JSONB;
ALTER TABLE users ADD COLUMN IF NOT EXISTS fav_artists JSONB;
ALTER TABLE users ADD COLUMN IF NOT EXISTS fav_vibe VARCHAR(50);
ALTER TABLE users ADD COLUMN IF NOT EXISTS avg_bpm INTEGER;
ALTER TABLE users ADD COLUMN IF NOT EXISTS preferred_hours JSONB;
ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarded BOOLEAN DEFAULT FALSE;

-- Micro-payments (F-02)
ALTER TABLE users ADD COLUMN IF NOT EXISTS ad_free_until TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS flac_credits INTEGER DEFAULT 0;

-- Referral system (E-01)
ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by BIGINT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_count INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_bonus_tracks INTEGER DEFAULT 0;

-- Version tracking
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen_version VARCHAR(20);
ALTER TABLE users ADD COLUMN IF NOT EXISTS welcome_sent BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS release_radar_enabled BOOLEAN DEFAULT TRUE;

-- Badges / Achievements
ALTER TABLE users ADD COLUMN IF NOT EXISTS badges JSONB;

-- Gamification (XP/Levels/Streaks)
ALTER TABLE users ADD COLUMN IF NOT EXISTS xp INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS level INTEGER DEFAULT 1;
ALTER TABLE users ADD COLUMN IF NOT EXISTS streak_days INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_play_date DATE;

-- Ensure timestamps columns exist
ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_active TIMESTAMPTZ DEFAULT NOW();

-- Family Plan tables (if missing)
CREATE TABLE IF NOT EXISTS family_plans (
    id SERIAL PRIMARY KEY,
    owner_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(100) DEFAULT 'Семейный план',
    max_members INTEGER DEFAULT 6,
    is_premium BOOLEAN DEFAULT FALSE,
    premium_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS family_members (
    id SERIAL PRIMARY KEY,
    family_id INTEGER NOT NULL REFERENCES family_plans(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(20) DEFAULT 'member',
    joined_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(family_id, user_id)
);

CREATE TABLE IF NOT EXISTS family_invites (
    id SERIAL PRIMARY KEY,
    family_id INTEGER NOT NULL REFERENCES family_plans(id) ON DELETE CASCADE,
    code VARCHAR(20) NOT NULL UNIQUE,
    created_by BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    used_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
    expires_at TIMESTAMPTZ,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Daily Mix tables
CREATE TABLE IF NOT EXISTS daily_mix_cache (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mix_type VARCHAR(50) DEFAULT 'daily',
    track_ids JSONB NOT NULL,
    generated_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_daily_mix_user ON daily_mix_cache(user_id, mix_type);

-- Artist Watchlist
CREATE TABLE IF NOT EXISTS artist_watchlist (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    artist_name VARCHAR(255) NOT NULL,
    artist_id VARCHAR(100),
    source VARCHAR(50) DEFAULT 'youtube',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, artist_name)
);
CREATE INDEX IF NOT EXISTS idx_watchlist_user ON artist_watchlist(user_id);

-- Release notifications
CREATE TABLE IF NOT EXISTS release_notifications (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    artist_name VARCHAR(255) NOT NULL,
    track_title VARCHAR(500) NOT NULL,
    video_id VARCHAR(50),
    notified_at TIMESTAMPTZ DEFAULT NOW(),
    clicked BOOLEAN DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_release_notif_user ON release_notifications(user_id);

-- Share links
CREATE TABLE IF NOT EXISTS share_links (
    id SERIAL PRIMARY KEY,
    code VARCHAR(20) NOT NULL UNIQUE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    track_id VARCHAR(100) NOT NULL,
    playlist_id INTEGER,
    click_count INTEGER DEFAULT 0,
    play_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_share_code ON share_links(code);

-- Recommendation logs
CREATE TABLE IF NOT EXISTS recommendation_logs (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    track_id VARCHAR(100) NOT NULL,
    score REAL,
    source VARCHAR(50),
    shown_at TIMESTAMPTZ DEFAULT NOW(),
    clicked BOOLEAN DEFAULT FALSE,
    played BOOLEAN DEFAULT FALSE,
    played_seconds INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_reco_log_user ON recommendation_logs(user_id, shown_at);

SELECT 'Migration completed successfully!' AS status;
