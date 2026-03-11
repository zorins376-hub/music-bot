-- ═══════════════════════════════════════════════════════════════════════════════
-- Migration 002: Core tables for AI recommendation engine
-- ═══════════════════════════════════════════════════════════════════════════════

-- ── Tracks ──────────────────────────────────────────────────────────────────────
create table if not exists tracks (
    id           bigint generated always as identity primary key,
    source_id    text unique not null,           -- "yt_xxx", "vk_123", etc.
    source       text not null default 'youtube', -- youtube | vk | spotify | channel
    channel      text,                            -- tequila | fullmoon | external
    title        text,
    artist       text,
    genre        text,
    bpm          smallint,
    duration     int,                             -- seconds
    file_id      text,                            -- Telegram file_id (if cached)
    downloads    int not null default 0,
    cover_url    text,                            -- album art URL
    embedding    extensions.vector(1536),          -- OpenAI text-embedding-3-small
    created_at   timestamptz not null default now()
);

create index if not exists ix_tracks_source_id on tracks (source_id);
create index if not exists ix_tracks_downloads on tracks (downloads desc);
create index if not exists ix_tracks_genre on tracks (genre) where genre is not null;
create index if not exists ix_tracks_artist on tracks (artist) where artist is not null;
create index if not exists ix_tracks_created on tracks (created_at desc);

-- HNSW index for fast vector search (cosine distance)
create index if not exists ix_tracks_embedding on tracks
    using hnsw (embedding extensions.vector_cosine_ops)
    with (m = 16, ef_construction = 64);


-- ── Users ───────────────────────────────────────────────────────────────────────
create table if not exists users (
    id                 bigint primary key,        -- Telegram user_id
    username           text,
    first_name         text,
    language           text not null default 'ru',
    is_premium         boolean not null default false,
    premium_until      timestamptz,
    created_at         timestamptz not null default now(),
    last_active        timestamptz not null default now()
);


-- ── User AI Profile (recalculated from history) ────────────────────────────────
create table if not exists user_profiles (
    user_id         bigint primary key references users(id) on delete cascade,
    fav_genres      text[] default '{}',            -- top 5 genres
    fav_artists     text[] default '{}',            -- top 5 artists
    fav_vibe        text,                            -- chill | energetic | melancholic…
    avg_bpm         smallint,
    preferred_hours smallint[] default '{}',         -- top 4 UTC hours
    taste_embedding extensions.vector(1536),         -- averaged embedding of liked tracks
    play_count      int not null default 0,          -- total plays
    like_count      int not null default 0,
    skip_count      int not null default 0,
    updated_at      timestamptz not null default now()
);


-- ── Listening History ───────────────────────────────────────────────────────────
create table if not exists listening_history (
    id              bigint generated always as identity primary key,
    user_id         bigint not null references users(id) on delete cascade,
    track_id        bigint references tracks(id) on delete set null,
    action          text not null default 'play',    -- play | skip | like | dislike
    listen_duration int,                              -- seconds actually listened
    source          text default 'search',            -- search | radio | automix | recommend | wave
    query           text,                             -- what user searched for
    created_at      timestamptz not null default now()
);

create index if not exists ix_lh_user_action on listening_history (user_id, action, created_at desc);
create index if not exists ix_lh_track on listening_history (track_id) where track_id is not null;
create index if not exists ix_lh_created on listening_history (created_at desc);


-- ── Recommendation Log (A/B testing) ────────────────────────────────────────────
create table if not exists recommendation_log (
    id          bigint generated always as identity primary key,
    user_id     bigint not null references users(id) on delete cascade,
    track_id    bigint not null references tracks(id) on delete cascade,
    algo        text not null,                       -- "hybrid" | "popular" | "content" | "collab"
    position    smallint not null,                   -- 0-indexed position in recommendation list
    score       double precision,
    clicked     boolean not null default false,
    created_at  timestamptz not null default now()
);

create index if not exists ix_reclog_user on recommendation_log (user_id, created_at desc);
create index if not exists ix_reclog_algo on recommendation_log (algo, created_at desc);


-- ── Playlists ───────────────────────────────────────────────────────────────────
create table if not exists playlists (
    id          bigint generated always as identity primary key,
    user_id     bigint not null references users(id) on delete cascade,
    name        text not null,
    created_at  timestamptz not null default now()
);

create index if not exists ix_playlists_user on playlists (user_id);

create table if not exists playlist_tracks (
    id          bigint generated always as identity primary key,
    playlist_id bigint not null references playlists(id) on delete cascade,
    track_id    bigint not null references tracks(id) on delete cascade,
    position    int not null default 0,
    added_at    timestamptz not null default now(),
    unique (playlist_id, track_id)
);


-- ── Embedding Queue (tracks pending embedding generation) ───────────────────────
create table if not exists embedding_queue (
    track_id    bigint primary key references tracks(id) on delete cascade,
    attempts    smallint not null default 0,
    last_error  text,
    created_at  timestamptz not null default now()
);


-- ── Row Level Security ──────────────────────────────────────────────────────────
-- Service role bypasses RLS; anon gets read-only on tracks
alter table tracks enable row level security;
alter table users enable row level security;
alter table user_profiles enable row level security;
alter table listening_history enable row level security;
alter table recommendation_log enable row level security;
alter table playlists enable row level security;
alter table playlist_tracks enable row level security;

-- Service role (used by Edge Functions) can do everything
create policy "service_all" on tracks for all using (true) with check (true);
create policy "service_all" on users for all using (true) with check (true);
create policy "service_all" on user_profiles for all using (true) with check (true);
create policy "service_all" on listening_history for all using (true) with check (true);
create policy "service_all" on recommendation_log for all using (true) with check (true);
create policy "service_all" on playlists for all using (true) with check (true);
create policy "service_all" on playlist_tracks for all using (true) with check (true);
