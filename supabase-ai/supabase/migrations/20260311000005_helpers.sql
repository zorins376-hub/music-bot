-- ═══════════════════════════════════════════════════════════════════════════════
-- Migration 005: Helper functions for Edge Functions
-- ═══════════════════════════════════════════════════════════════════════════════

set search_path to public, extensions;

-- ── Increment downloads atomically ──────────────────────────────────────────────
create or replace function increment_downloads(p_track_id bigint)
returns void
language sql
as $$
    update tracks set downloads = downloads + 1 where id = p_track_id;
$$;


-- ── Match tracks by embedding vector (for AI playlist) ─────────────────────────
create or replace function match_tracks_by_embedding(
    query_embedding vector(1536),
    match_threshold double precision default 0.3,
    match_count int default 10
)
returns table (
    id          bigint,
    source_id   text,
    title       text,
    artist      text,
    genre       text,
    duration    int,
    cover_url   text,
    similarity  double precision
)
language sql stable
set search_path = public, extensions
as $$
    select
        t.id,
        t.source_id,
        t.title,
        t.artist,
        t.genre,
        t.duration,
        t.cover_url,
        1.0 - (t.embedding <=> query_embedding) as similarity
    from tracks t
    where t.embedding is not null
      and t.file_id is not null
      and 1.0 - (t.embedding <=> query_embedding) > match_threshold
    order by t.embedding <=> query_embedding
    limit match_count;
$$;


-- ── Sync user from bot (upsert with all fields) ────────────────────────────────
create or replace function sync_user(
    p_id          bigint,
    p_username    text default null,
    p_first_name  text default null,
    p_language    text default 'ru',
    p_is_premium  boolean default false
)
returns void
language sql
as $$
    insert into users (id, username, first_name, language, is_premium, last_active)
    values (p_id, p_username, p_first_name, p_language, p_is_premium, now())
    on conflict (id) do update set
        username    = coalesce(excluded.username, users.username),
        first_name  = coalesce(excluded.first_name, users.first_name),
        language    = excluded.language,
        is_premium  = excluded.is_premium,
        last_active = now();
$$;
