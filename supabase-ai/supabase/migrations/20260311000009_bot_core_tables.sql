-- ═══════════════════════════════════════════════════════════════════════════════
-- Migration 009: Bot core tables — move main DB from Railway to Supabase
--
-- Extends existing AI engine tables (users, tracks) with bot-specific columns
-- and creates all remaining bot tables (22 total).
-- ═══════════════════════════════════════════════════════════════════════════════

-- ── pg_trgm extension (fuzzy search) ────────────────────────────────────────
create extension if not exists pg_trgm;

-- ═══════════════════════════════════════════════════════════════════════════════
-- 1. Extend existing `users` table with bot-specific columns
-- ═══════════════════════════════════════════════════════════════════════════════
alter table users add column if not exists quality         varchar(10)  default '192';
alter table users add column if not exists is_banned       boolean      default false;
alter table users add column if not exists is_admin        boolean      default false;
alter table users add column if not exists captcha_passed  boolean      default false;
alter table users add column if not exists request_count   integer      default 0;
alter table users add column if not exists fav_genres      jsonb;
alter table users add column if not exists fav_artists     jsonb;
alter table users add column if not exists fav_vibe        varchar(50);
alter table users add column if not exists avg_bpm         integer;
alter table users add column if not exists preferred_hours jsonb;
alter table users add column if not exists onboarded       boolean      default false;
alter table users add column if not exists ad_free_until   timestamptz;
alter table users add column if not exists flac_credits    integer      default 0;
alter table users add column if not exists referred_by     bigint;
alter table users add column if not exists referral_count  integer      default 0;
alter table users add column if not exists referral_bonus_tracks integer default 0;
alter table users add column if not exists last_seen_version varchar(20);
alter table users add column if not exists welcome_sent    boolean      default false;
alter table users add column if not exists release_radar_enabled boolean default true;
alter table users add column if not exists badges          jsonb;
alter table users add column if not exists xp              integer      default 0;
alter table users add column if not exists level           integer      default 1;
alter table users add column if not exists streak_days     integer      default 0;
alter table users add column if not exists last_play_date  date;

-- ═══════════════════════════════════════════════════════════════════════════════
-- 2. Extend existing `tracks` table (ensure all bot columns exist)
-- ═══════════════════════════════════════════════════════════════════════════════
alter table tracks add column if not exists source    varchar(20)  default 'youtube';
alter table tracks add column if not exists channel   varchar(50);
alter table tracks add column if not exists artist    varchar(255);
alter table tracks add column if not exists genre     varchar(50);
alter table tracks add column if not exists bpm       integer;
alter table tracks add column if not exists duration  integer;
alter table tracks add column if not exists downloads integer      default 0;
alter table tracks add column if not exists file_id   varchar(255);

-- Trigram GIN indexes for fuzzy search
create index if not exists ix_tracks_title_trgm
    on tracks using gin (title gin_trgm_ops);
create index if not exists ix_tracks_artist_trgm
    on tracks using gin (artist gin_trgm_ops);

-- ═══════════════════════════════════════════════════════════════════════════════
-- 3. listening_history — highest-volume table (plays, likes, skips)
-- ═══════════════════════════════════════════════════════════════════════════════
create table if not exists listening_history (
    id              integer generated always as identity primary key,
    user_id         bigint        not null references users(id),
    track_id        integer       references tracks(id),
    query           varchar(500),
    action          varchar(20)   default 'play',
    listen_duration integer,
    source          varchar(20)   default 'search',
    created_at      timestamptz   not null default now()
);

create index if not exists ix_lh_user_action_created
    on listening_history (user_id, action, created_at desc);
create index if not exists ix_lh_track_id
    on listening_history (track_id) where track_id is not null;
create index if not exists ix_lh_created_at
    on listening_history (created_at desc);

-- ═══════════════════════════════════════════════════════════════════════════════
-- 4. payments — Telegram Stars transactions
-- ═══════════════════════════════════════════════════════════════════════════════
create table if not exists payments (
    id         integer generated always as identity primary key,
    user_id    bigint       not null references users(id),
    amount     integer      not null,
    currency   varchar(10)  default 'XTR',
    payload    varchar(100),
    created_at timestamptz  not null default now()
);

create index if not exists ix_payments_user_id on payments (user_id);

-- ═══════════════════════════════════════════════════════════════════════════════
-- 5. playlists + playlist_tracks
-- ═══════════════════════════════════════════════════════════════════════════════
create table if not exists playlists (
    id         integer generated always as identity primary key,
    user_id    bigint        not null references users(id),
    name       varchar(100)  not null,
    created_at timestamptz   not null default now()
);

create index if not exists ix_playlists_user_id on playlists (user_id);

create table if not exists playlist_tracks (
    id          integer generated always as identity primary key,
    playlist_id integer not null references playlists(id) on delete cascade,
    track_id    integer not null references tracks(id),
    position    integer default 0,
    added_at    timestamptz not null default now(),
    unique (playlist_id, track_id)
);

create index if not exists ix_playlist_tracks_playlist_id on playlist_tracks (playlist_id);

-- ═══════════════════════════════════════════════════════════════════════════════
-- 6. favorite_tracks
-- ═══════════════════════════════════════════════════════════════════════════════
create table if not exists favorite_tracks (
    id         integer generated always as identity primary key,
    user_id    bigint   not null references users(id),
    track_id   integer  not null references tracks(id),
    created_at timestamptz not null default now(),
    unique (user_id, track_id)
);

create index if not exists ix_favorites_user_id on favorite_tracks (user_id);
create index if not exists ix_favorites_track_id on favorite_tracks (track_id);
create index if not exists ix_favorites_user_created on favorite_tracks (user_id, created_at);

-- ═══════════════════════════════════════════════════════════════════════════════
-- 7. release_notifications
-- ═══════════════════════════════════════════════════════════════════════════════
create table if not exists release_notifications (
    id        integer generated always as identity primary key,
    user_id   bigint       not null,
    track_id  integer      not null,
    artist    varchar(255),
    title     varchar(500),
    sent_at   timestamptz  not null default now(),
    opened_at timestamptz,
    unique (user_id, track_id)
);

create index if not exists ix_release_notif_user_id on release_notifications (user_id);
create index if not exists ix_release_notif_track_id on release_notifications (track_id);

-- ═══════════════════════════════════════════════════════════════════════════════
-- 8. admin_log
-- ═══════════════════════════════════════════════════════════════════════════════
create table if not exists admin_log (
    id             integer generated always as identity primary key,
    admin_id       bigint       not null,
    action         varchar(50)  not null,
    target_user_id bigint,
    details        text,
    created_at     timestamptz  not null default now()
);

create index if not exists ix_admin_log_admin_id on admin_log (admin_id);
create index if not exists ix_admin_log_created_at on admin_log (created_at);

-- ═══════════════════════════════════════════════════════════════════════════════
-- 9. blocked_tracks (DMCA)
-- ═══════════════════════════════════════════════════════════════════════════════
create table if not exists blocked_tracks (
    id                   integer generated always as identity primary key,
    source_id            varchar(100) unique not null,
    reason               varchar(255) default 'DMCA',
    blocked_by           varchar(100),
    alternative_source_id varchar(100),
    created_at           timestamptz  not null default now()
);

create index if not exists ix_blocked_tracks_source_id on blocked_tracks (source_id);

-- ═══════════════════════════════════════════════════════════════════════════════
-- 10. promo_codes + promo_activations
-- ═══════════════════════════════════════════════════════════════════════════════
create table if not exists promo_codes (
    id         integer generated always as identity primary key,
    code       varchar(50) unique not null,
    promo_type varchar(30)  not null,
    uses_left  integer      default 1,
    max_uses   integer      default 1,
    created_by bigint,
    created_at timestamptz  not null default now()
);

create index if not exists ix_promo_codes_code on promo_codes (code);

create table if not exists promo_activations (
    id           integer generated always as identity primary key,
    promo_id     integer not null references promo_codes(id),
    user_id      bigint  not null,
    activated_at timestamptz not null default now(),
    unique (promo_id, user_id)
);

-- ═══════════════════════════════════════════════════════════════════════════════
-- 11. sponsored_campaigns + sponsored_events
-- ═══════════════════════════════════════════════════════════════════════════════
create table if not exists sponsored_campaigns (
    id               integer generated always as identity primary key,
    user_id          bigint  not null,
    track_id         integer references tracks(id),
    budget_stars     integer default 0,
    spent_stars      integer default 0,
    impressions_total integer default 0,
    clicks_total     integer default 0,
    target_genres    jsonb,
    status           varchar(20) default 'pending',
    approved_by      bigint,
    created_at       timestamptz not null default now()
);

create index if not exists ix_sponsored_campaigns_user_id on sponsored_campaigns (user_id);

create table if not exists sponsored_events (
    id           integer generated always as identity primary key,
    campaign_id  integer     not null references sponsored_campaigns(id),
    user_id      bigint      not null,
    event_type   varchar(20) not null,
    created_at   timestamptz not null default now()
);

create index if not exists ix_sponsored_events_campaign_id on sponsored_events (campaign_id);

-- ═══════════════════════════════════════════════════════════════════════════════
-- 12. dmca_appeals
-- ═══════════════════════════════════════════════════════════════════════════════
create table if not exists dmca_appeals (
    id               integer generated always as identity primary key,
    user_id          bigint  not null,
    blocked_track_id integer references blocked_tracks(id),
    reason           text    default '',
    status           varchar(20) default 'pending',
    reviewed_by      bigint,
    created_at       timestamptz not null default now()
);

create index if not exists ix_dmca_appeals_user_id on dmca_appeals (user_id);

-- ═══════════════════════════════════════════════════════════════════════════════
-- 13. daily_mixes + daily_mix_tracks
-- ═══════════════════════════════════════════════════════════════════════════════
create table if not exists daily_mixes (
    id         integer generated always as identity primary key,
    user_id    bigint       not null references users(id),
    mix_date   date         not null,
    title      varchar(120) default 'Daily Mix',
    source     varchar(20)  default 'daily_mix',
    created_at timestamptz  not null default now(),
    unique (user_id, mix_date)
);

create index if not exists ix_daily_mixes_user_id on daily_mixes (user_id);
create index if not exists ix_daily_mixes_mix_date on daily_mixes (mix_date);

create table if not exists daily_mix_tracks (
    id       integer generated always as identity primary key,
    mix_id   integer not null references daily_mixes(id) on delete cascade,
    track_id integer not null references tracks(id),
    position integer not null,
    score    double precision,
    reason   varchar(255),
    unique (mix_id, track_id)
);

create index if not exists ix_daily_mix_tracks_mix_id on daily_mix_tracks (mix_id);
create index if not exists ix_daily_mix_tracks_mix_pos on daily_mix_tracks (mix_id, position);

-- ═══════════════════════════════════════════════════════════════════════════════
-- 14. share_links
-- ═══════════════════════════════════════════════════════════════════════════════
create table if not exists share_links (
    id          integer generated always as identity primary key,
    owner_id    bigint       not null,
    entity_type varchar(20)  not null,
    entity_id   integer      default 0,
    short_code  varchar(32)  unique not null,
    payload     text,
    clicks      integer      default 0,
    expires_at  timestamptz,
    created_at  timestamptz  not null default now()
);

create index if not exists ix_share_links_owner_id on share_links (owner_id);
create index if not exists ix_share_links_short_code on share_links (short_code);
create index if not exists ix_share_links_entity_type on share_links (entity_type);

-- ═══════════════════════════════════════════════════════════════════════════════
-- 15. artist_watchlist (Release Radar)
-- ═══════════════════════════════════════════════════════════════════════════════
create table if not exists artist_watchlist (
    id              integer generated always as identity primary key,
    user_id         bigint       not null,
    artist_name     varchar(255) not null,
    normalized_name varchar(255) not null,
    source          varchar(20)  default 'auto',
    weight          double precision default 1.0,
    created_at      timestamptz  not null default now(),
    unique (user_id, normalized_name)
);

create index if not exists ix_artist_watchlist_user_id on artist_watchlist (user_id);
create index if not exists ix_artist_watchlist_normalized on artist_watchlist (normalized_name);

-- ═══════════════════════════════════════════════════════════════════════════════
-- 16. family_plans + family_members + family_invites
-- ═══════════════════════════════════════════════════════════════════════════════
create table if not exists family_plans (
    id            integer generated always as identity primary key,
    owner_id      bigint       unique not null,
    name          varchar(100) default 'Моя семья',
    max_members   integer      default 5,
    is_active     boolean      default true,
    premium_until timestamptz,
    created_at    timestamptz  not null default now()
);

create index if not exists ix_family_plans_owner_id on family_plans (owner_id);

create table if not exists family_members (
    id             integer generated always as identity primary key,
    family_plan_id integer     not null references family_plans(id) on delete cascade,
    user_id        bigint      unique not null,
    role           varchar(20) default 'member',
    joined_at      timestamptz not null default now()
);

create index if not exists ix_family_members_plan_id on family_members (family_plan_id);
create index if not exists ix_family_members_user_id on family_members (user_id);

create table if not exists family_invites (
    id             integer generated always as identity primary key,
    family_plan_id integer     not null references family_plans(id) on delete cascade,
    invite_code    varchar(20) unique not null,
    uses_left      integer     default 1,
    expires_at     timestamptz,
    created_at     timestamptz not null default now()
);

create index if not exists ix_family_invites_plan_id on family_invites (family_plan_id);
create index if not exists ix_family_invites_code on family_invites (invite_code);

-- ═══════════════════════════════════════════════════════════════════════════════
-- 17. recommendation_log (A/B testing)
-- ═══════════════════════════════════════════════════════════════════════════════
create table if not exists recommendation_log (
    id          integer generated always as identity primary key,
    user_id     bigint       not null,
    variant     varchar(20)  not null,
    track_ids   jsonb,
    scores      jsonb,
    clicked     boolean      default false,
    created_at  timestamptz  not null default now()
);

create index if not exists ix_reco_log_user_id on recommendation_log (user_id);
create index if not exists ix_reco_log_created on recommendation_log (created_at desc);

-- ═══════════════════════════════════════════════════════════════════════════════
-- Done: 22 bot tables ready (users, tracks extended + 20 new tables created)
-- ═══════════════════════════════════════════════════════════════════════════════
