-- ═══════════════════════════════════════════════════════════════════════════════
-- Migration 006: Trending tracks + Feedback loop
-- ═══════════════════════════════════════════════════════════════════════════════

set search_path to public, extensions;

-- ═════════════════════════════════════════════════════════════════════════════════
-- TRENDING: Real-time trending based on play velocity
-- ═════════════════════════════════════════════════════════════════════════════════

create or replace function trending_tracks(
    p_hours    int default 24,
    p_limit    int default 20,
    p_genre    text default null
)
returns table (
    track_id      bigint,
    source_id     text,
    title         text,
    artist        text,
    genre         text,
    duration      int,
    cover_url     text,
    play_count    bigint,
    unique_users  bigint,
    velocity      double precision,
    trend         text
)
language sql stable
set search_path = public, extensions
as $$
    with recent_plays as (
        select
            lh.track_id,
            count(*) as play_count,
            count(distinct lh.user_id) as unique_users,
            -- velocity = plays per hour, weighted by recency
            count(*)::double precision / greatest(p_hours, 1) as velocity
        from listening_history lh
        where lh.action = 'play'
          and lh.created_at > now() - make_interval(hours => p_hours)
          and lh.track_id is not null
        group by lh.track_id
        having count(distinct lh.user_id) >= 2  -- at least 2 different users
    ),
    prev_period as (
        select
            lh.track_id,
            count(*) as prev_count
        from listening_history lh
        where lh.action = 'play'
          and lh.created_at between
              now() - make_interval(hours => p_hours * 2)
              and now() - make_interval(hours => p_hours)
          and lh.track_id is not null
        group by lh.track_id
    )
    select
        t.id as track_id,
        t.source_id,
        t.title,
        t.artist,
        t.genre,
        t.duration,
        t.cover_url,
        rp.play_count,
        rp.unique_users,
        rp.velocity,
        case
            when pp.prev_count is null or pp.prev_count = 0 then 'new'
            when rp.play_count > pp.prev_count * 2 then 'hot'
            when rp.play_count > pp.prev_count then 'rising'
            when rp.play_count < pp.prev_count then 'falling'
            else 'stable'
        end as trend
    from recent_plays rp
    join tracks t on t.id = rp.track_id
    left join prev_period pp on pp.track_id = rp.track_id
    where (p_genre is null or t.genre = p_genre)
    order by rp.velocity desc, rp.unique_users desc
    limit p_limit;
$$;


-- ═════════════════════════════════════════════════════════════════════════════════
-- FEEDBACK: Record explicit user feedback for better learning
-- ═════════════════════════════════════════════════════════════════════════════════

create table if not exists user_feedback (
    id          bigint generated always as identity primary key,
    user_id     bigint not null references users(id),
    track_id    bigint references tracks(id),
    source_id   text,
    feedback    text not null check (feedback in ('like', 'dislike', 'skip', 'save', 'share', 'repeat')),
    context     text,  -- 'recommend', 'search', 'radio', 'playlist', 'trending'
    created_at  timestamptz default now()
);

create index if not exists idx_feedback_user   on user_feedback(user_id, created_at desc);
create index if not exists idx_feedback_track  on user_feedback(track_id);

alter table user_feedback enable row level security;
create policy "service_all" on user_feedback for all using (true);


-- ═════════════════════════════════════════════════════════════════════════════════
-- USER TASTE SUMMARY: Quick stats for user profile display
-- ═════════════════════════════════════════════════════════════════════════════════

create or replace function user_taste_summary(p_user_id bigint)
returns jsonb
language sql stable
as $$
    select jsonb_build_object(
        'top_genres', (
            select coalesce(jsonb_agg(jsonb_build_object('genre', g, 'count', cnt)), '[]'::jsonb)
            from (
                select t.genre as g, count(*) as cnt
                from listening_history lh
                join tracks t on t.id = lh.track_id
                where lh.user_id = p_user_id
                  and lh.action in ('play', 'like')
                  and t.genre is not null
                  and lh.created_at > now() - interval '90 days'
                group by t.genre order by cnt desc limit 5
            ) sub
        ),
        'top_artists', (
            select coalesce(jsonb_agg(jsonb_build_object('artist', a, 'count', cnt)), '[]'::jsonb)
            from (
                select t.artist as a, count(*) as cnt
                from listening_history lh
                join tracks t on t.id = lh.track_id
                where lh.user_id = p_user_id
                  and lh.action in ('play', 'like')
                  and t.artist is not null
                  and lh.created_at > now() - interval '90 days'
                group by t.artist order by cnt desc limit 5
            ) sub
        ),
        'total_plays', (
            select count(*) from listening_history
            where user_id = p_user_id and action = 'play'
        ),
        'total_likes', (
            select count(*) from user_feedback
            where user_id = p_user_id and feedback = 'like'
        ),
        'listening_hours', (
            select round(coalesce(sum(lh.listen_duration), 0) / 3600.0, 1)
            from listening_history lh
            where lh.user_id = p_user_id and lh.action = 'play'
        ),
        'vibe', (
            select fav_vibe from user_profiles where user_id = p_user_id
        ),
        'member_since', (
            select created_at from users where id = p_user_id
        )
    );
$$;


-- ═════════════════════════════════════════════════════════════════════════════════
-- SMART SEARCH: Full-text search with ranking across tracks
-- ═════════════════════════════════════════════════════════════════════════════════

-- Add tsvector column for full-text search
alter table tracks add column if not exists tsv tsvector;

create or replace function tracks_tsv_trigger() returns trigger
language plpgsql as $$
begin
    new.tsv := to_tsvector('simple',
        coalesce(new.title, '') || ' ' ||
        coalesce(new.artist, '') || ' ' ||
        coalesce(new.genre, '')
    );
    return new;
end;
$$;

drop trigger if exists trg_tracks_tsv on tracks;
create trigger trg_tracks_tsv
    before insert or update of title, artist, genre on tracks
    for each row execute function tracks_tsv_trigger();

-- Backfill existing tracks
update tracks set tsv = to_tsvector('simple',
    coalesce(title, '') || ' ' || coalesce(artist, '') || ' ' || coalesce(genre, '')
)
where tsv is null;

create index if not exists idx_tracks_tsv on tracks using gin(tsv);

create or replace function search_tracks(
    p_query   text,
    p_limit   int default 20,
    p_genre   text default null
)
returns table (
    track_id    bigint,
    source_id   text,
    title       text,
    artist      text,
    genre       text,
    duration    int,
    cover_url   text,
    downloads   int,
    rank        real
)
language sql stable
as $$
    select
        t.id as track_id,
        t.source_id,
        t.title,
        t.artist,
        t.genre,
        t.duration,
        t.cover_url,
        t.downloads,
        ts_rank(t.tsv, websearch_to_tsquery('simple', p_query)) as rank
    from tracks t
    where t.tsv @@ websearch_to_tsquery('simple', p_query)
      and t.file_id is not null
      and (p_genre is null or t.genre = p_genre)
    order by rank desc, t.downloads desc
    limit p_limit;
$$;
