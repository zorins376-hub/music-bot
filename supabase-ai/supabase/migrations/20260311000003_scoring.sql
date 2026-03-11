-- ═══════════════════════════════════════════════════════════════════════════════
-- Migration 003: Scoring functions — the heart of the recommendation engine
--
-- Hybrid scoring: vector similarity + popularity + freshness + time-of-day
-- All computation happens in PostgreSQL — fast, no external ML runtime needed
-- ═══════════════════════════════════════════════════════════════════════════════

-- ── Helper: cosine similarity between two vectors ───────────────────────────────
-- pgvector provides <=> (cosine distance), we convert to similarity = 1 - distance
-- This is used internally by the scoring functions.


-- ═════════════════════════════════════════════════════════════════════════════════
-- RECOMMEND: Main hybrid recommendation function
--
-- Components (weights configurable):
--   1. Embedding similarity  (w_embed=0.35) — cosine sim of user taste → track
--   2. Popularity             (w_pop=0.20)   — normalized download count
--   3. Freshness              (w_fresh=0.15) — exponential decay over 30 days
--   4. Genre match            (w_genre=0.15) — 1.0 if in user's fav genres
--   5. Time-of-day            (w_time=0.10)  — boost if current hour ∈ preferred
--   6. Diversity penalty      (w_div=0.05)   — penalize already-seen artists
--
-- Returns scored tracks sorted by final_score DESC
-- ═════════════════════════════════════════════════════════════════════════════════

create or replace function recommend_tracks(
    p_user_id     bigint,
    p_limit       int default 20,
    p_w_embed     double precision default 0.35,
    p_w_pop       double precision default 0.20,
    p_w_fresh     double precision default 0.15,
    p_w_genre     double precision default 0.15,
    p_w_time      double precision default 0.10,
    p_w_div       double precision default 0.05
)
returns table (
    track_id      bigint,
    source_id     text,
    title         text,
    artist        text,
    genre         text,
    duration      int,
    cover_url     text,
    downloads     int,
    final_score   double precision,
    s_embed       double precision,
    s_pop         double precision,
    s_fresh       double precision,
    s_genre       double precision,
    s_time        double precision,
    algo          text
)
language plpgsql stable
as $$
declare
    v_taste      extensions.vector(1536);
    v_genres     text[];
    v_hours      smallint[];
    v_hour       smallint;
    v_max_dl     double precision;
    v_listened   bigint[];
    v_has_embed  boolean;
begin
    -- ── 1. Load user profile ─────────────────────────────────────────────
    select
        up.taste_embedding,
        up.fav_genres,
        up.preferred_hours
    into v_taste, v_genres, v_hours
    from user_profiles up
    where up.user_id = p_user_id;

    v_hour := extract(hour from now() at time zone 'utc')::smallint;
    v_has_embed := v_taste is not null;

    -- ── 2. Get tracks user already listened to (last 90 days) ────────────
    select array_agg(distinct lh.track_id)
    into v_listened
    from listening_history lh
    where lh.user_id = p_user_id
      and lh.track_id is not null
      and lh.created_at > now() - interval '90 days';

    if v_listened is null then
        v_listened := '{}';
    end if;

    -- ── 3. Max downloads for normalization ───────────────────────────────
    select coalesce(max(t.downloads), 1)::double precision
    into v_max_dl
    from tracks t
    where t.file_id is not null;

    -- ── 4. Score and return ──────────────────────────────────────────────
    return query
    with candidates as (
        -- Get candidate tracks:
        -- If user has taste embedding → vector similarity search (top 200)
        -- Otherwise → popular tracks from last 30 days
        select t.*
        from tracks t
        where t.file_id is not null
          and t.id != all(v_listened)
          and (
              -- Vector search path
              (v_has_embed and t.embedding is not null)
              or
              -- Popularity fallback
              (not v_has_embed and t.created_at > now() - interval '30 days')
          )
        order by
            case when v_has_embed and t.embedding is not null
                 then 1.0 - (t.embedding extensions.<=> v_taste)
                 else t.downloads::double precision / v_max_dl
            end desc
        limit 200
    ),
    scored as (
        select
            c.id as track_id,
            c.source_id,
            c.title,
            c.artist,
            c.genre,
            c.duration,
            c.cover_url,
            c.downloads,

            -- Embedding similarity (0..1)
            case when v_has_embed and c.embedding is not null
                 then greatest(0, 1.0 - (c.embedding extensions.<=> v_taste))
                 else 0.5
            end as s_embed,

            -- Popularity (0..1)
            c.downloads::double precision / v_max_dl as s_pop,

            -- Freshness (0..1, exponential decay 30 days)
            greatest(0, 1.0 - extract(epoch from now() - c.created_at) / (30.0 * 86400)) as s_fresh,

            -- Genre match (1.0 if matching, 0.3 default)
            case when c.genre is not null and v_genres is not null
                      and c.genre = any(v_genres)
                 then 1.0
                 else 0.3
            end as s_genre,

            -- Time-of-day (1.0 exact, 0.5 ±1h, 0 otherwise)
            case when v_hours is not null and v_hour = any(v_hours) then 1.0
                 when v_hours is not null and (v_hour + 1)::smallint = any(v_hours) then 0.5
                 when v_hours is not null and (v_hour - 1)::smallint = any(v_hours) then 0.5
                 else 0.0
            end as s_time,

            -- Algo label
            case when v_has_embed then 'hybrid' else 'popular' end as algo

        from candidates c
    ),
    diversified as (
        select
            s.*,
            -- Weighted sum
            (p_w_embed * s.s_embed
             + p_w_pop  * s.s_pop
             + p_w_fresh * s.s_fresh
             + p_w_genre * s.s_genre
             + p_w_time  * s.s_time
            ) as final_score,
            row_number() over (partition by s.artist order by
                (p_w_embed * s.s_embed + p_w_pop * s.s_pop + p_w_fresh * s.s_fresh) desc
            ) as artist_rank
        from scored s
    )
    select
        d.track_id,
        d.source_id,
        d.title,
        d.artist,
        d.genre,
        d.duration,
        d.cover_url,
        d.downloads,
        d.final_score,
        d.s_embed,
        d.s_pop,
        d.s_fresh,
        d.s_genre,
        d.s_time,
        d.algo
    from diversified d
    where d.artist_rank <= 2  -- max 2 tracks per artist
    order by d.final_score desc
    limit p_limit;
end;
$$;


-- ═════════════════════════════════════════════════════════════════════════════════
-- UPDATE USER PROFILE: Recalculate taste from listening history
-- ═════════════════════════════════════════════════════════════════════════════════

create or replace function update_user_profile(p_user_id bigint)
returns void
language plpgsql
as $$
declare
    v_genres      text[];
    v_artists     text[];
    v_avg_bpm     smallint;
    v_hours       smallint[];
    v_taste       extensions.vector(1536);
    v_play_count  int;
    v_like_count  int;
    v_skip_count  int;
    v_vibe        text;
begin
    -- ── Top 5 genres (recency-weighted) ──────────────────────────────────
    select array_agg(g order by cnt desc)
    into v_genres
    from (
        select t.genre as g, count(*) as cnt
        from listening_history lh
        join tracks t on t.id = lh.track_id
        where lh.user_id = p_user_id
          and lh.action in ('play', 'like')
          and t.genre is not null
          and lh.created_at > now() - interval '90 days'
        group by t.genre
        order by cnt desc
        limit 5
    ) sub;

    -- ── Top 5 artists ───────────────────────────────────────────────────
    select array_agg(a order by cnt desc)
    into v_artists
    from (
        select t.artist as a, count(*) as cnt
        from listening_history lh
        join tracks t on t.id = lh.track_id
        where lh.user_id = p_user_id
          and lh.action in ('play', 'like')
          and t.artist is not null
          and lh.created_at > now() - interval '90 days'
        group by t.artist
        order by cnt desc
        limit 5
    ) sub;

    -- ── Average BPM (last 100 tracks) ───────────────────────────────────
    select avg(t.bpm)::smallint
    into v_avg_bpm
    from (
        select t2.bpm
        from listening_history lh
        join tracks t2 on t2.id = lh.track_id
        where lh.user_id = p_user_id
          and lh.action = 'play'
          and t2.bpm is not null
        order by lh.created_at desc
        limit 100
    ) t;

    -- ── Preferred hours (top 4) ─────────────────────────────────────────
    select array_agg(h order by cnt desc)
    into v_hours
    from (
        select extract(hour from lh.created_at at time zone 'utc')::smallint as h,
               count(*) as cnt
        from listening_history lh
        where lh.user_id = p_user_id
          and lh.action = 'play'
          and lh.created_at > now() - interval '30 days'
        group by h
        order by cnt desc
        limit 4
    ) sub;

    -- ── Taste embedding: avg of embeddings of liked/played tracks ───────
    select avg(t.embedding)::extensions.vector(1536)
    into v_taste
    from listening_history lh
    join tracks t on t.id = lh.track_id
    where lh.user_id = p_user_id
      and lh.action in ('play', 'like')
      and t.embedding is not null
      and lh.created_at > now() - interval '60 days'
    limit 500;

    -- ── Counters ────────────────────────────────────────────────────────
    select count(*) filter (where action = 'play'),
           count(*) filter (where action = 'like'),
           count(*) filter (where action = 'skip')
    into v_play_count, v_like_count, v_skip_count
    from listening_history
    where user_id = p_user_id;

    -- ── Infer vibe from BPM + genres ────────────────────────────────────
    v_vibe := case
        when v_avg_bpm is null then null
        when v_avg_bpm < 90 then 'chill'
        when v_avg_bpm < 110 then 'mellow'
        when v_avg_bpm < 130 then 'energetic'
        else 'intense'
    end;

    -- Refine by genre
    if v_genres is not null then
        if 'lofi' = any(v_genres) or 'ambient' = any(v_genres) then
            v_vibe := 'chill';
        elsif 'metal' = any(v_genres) or 'punk' = any(v_genres) then
            v_vibe := 'intense';
        elsif 'electronic' = any(v_genres) or 'edm' = any(v_genres) then
            v_vibe := 'energetic';
        elsif 'jazz' = any(v_genres) or 'soul' = any(v_genres) then
            v_vibe := 'mellow';
        end if;
    end if;

    -- ── Upsert profile ──────────────────────────────────────────────────
    insert into user_profiles (
        user_id, fav_genres, fav_artists, fav_vibe, avg_bpm,
        preferred_hours, taste_embedding, play_count, like_count, skip_count, updated_at
    )
    values (
        p_user_id, coalesce(v_genres, '{}'), coalesce(v_artists, '{}'),
        v_vibe, v_avg_bpm, coalesce(v_hours, '{}'),
        v_taste, v_play_count, v_like_count, v_skip_count, now()
    )
    on conflict (user_id) do update set
        fav_genres      = coalesce(excluded.fav_genres, user_profiles.fav_genres),
        fav_artists     = coalesce(excluded.fav_artists, user_profiles.fav_artists),
        fav_vibe        = coalesce(excluded.fav_vibe, user_profiles.fav_vibe),
        avg_bpm         = coalesce(excluded.avg_bpm, user_profiles.avg_bpm),
        preferred_hours = coalesce(excluded.preferred_hours, user_profiles.preferred_hours),
        taste_embedding = coalesce(excluded.taste_embedding, user_profiles.taste_embedding),
        play_count      = excluded.play_count,
        like_count      = excluded.like_count,
        skip_count      = excluded.skip_count,
        updated_at      = now();
end;
$$;


-- ═════════════════════════════════════════════════════════════════════════════════
-- SIMILAR TRACKS: Find tracks similar to a given track by embedding
-- ═════════════════════════════════════════════════════════════════════════════════

create or replace function similar_tracks(
    p_track_id    bigint,
    p_limit       int default 10
)
returns table (
    track_id      bigint,
    source_id     text,
    title         text,
    artist        text,
    genre         text,
    similarity    double precision
)
language sql stable
as $$
    with src as (
        select embedding from tracks where id = p_track_id
    )
    select
        t.id as track_id,
        t.source_id,
        t.title,
        t.artist,
        t.genre,
        1.0 - (t.embedding extensions.<=> src.embedding) as similarity
    from tracks t, src
    where t.id != p_track_id
      and t.embedding is not null
      and src.embedding is not null
      and t.file_id is not null
    order by t.embedding extensions.<=> src.embedding
    limit p_limit;
$$;


-- ═════════════════════════════════════════════════════════════════════════════════
-- A/B TESTING: CTR report by algo
-- ═════════════════════════════════════════════════════════════════════════════════

create or replace function ab_test_report(p_days int default 7)
returns table (
    algo         text,
    total_shown  bigint,
    total_clicks bigint,
    ctr          double precision,
    avg_position double precision
)
language sql stable
as $$
    select
        rl.algo,
        count(*) as total_shown,
        count(*) filter (where rl.clicked) as total_clicks,
        count(*) filter (where rl.clicked)::double precision / nullif(count(*), 0) as ctr,
        avg(rl.position) filter (where rl.clicked) as avg_position
    from recommendation_log rl
    where rl.created_at > now() - make_interval(days => p_days)
    group by rl.algo
    order by ctr desc;
$$;
