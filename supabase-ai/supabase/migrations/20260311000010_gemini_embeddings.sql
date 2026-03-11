-- ═══════════════════════════════════════════════════════════════════════════════
-- Migration 010: Switch from OpenAI (1536d) to Google Gemini (768d) embeddings
--
-- text-embedding-004 produces 768-dimensional vectors (free tier).
-- No embedded tracks exist yet, so safe to alter column dimensions.
-- ═══════════════════════════════════════════════════════════════════════════════

set search_path to public, extensions;

-- ── 1. Drop the HNSW index (cannot alter column with index) ─────────────────
drop index if exists idx_tracks_embedding;

-- ── 2. Alter embedding columns: 1536 → 768 ─────────────────────────────────
alter table tracks
    alter column embedding type vector(768) using null;

alter table user_profiles
    alter column taste_embedding type vector(768) using null;

-- ── 3. Recreate HNSW index with new dimensions ─────────────────────────────
create index idx_tracks_embedding
    on tracks using hnsw (embedding vector_cosine_ops)
    with (m = 16, ef_construction = 64);


-- ══════════════════════════════════════════════════════════════════════════════
-- 4. Rebuild all functions that reference vector(1536) → vector(768)
-- ══════════════════════════════════════════════════════════════════════════════

-- ── match_tracks_by_embedding (ai-playlist vector search) ───────────────────
create or replace function match_tracks_by_embedding(
    query_embedding vector(768),
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


-- ── update_user_profile (taste embedding averaging) ─────────────────────────
create or replace function update_user_profile(p_user_id bigint)
returns void
language plpgsql
set search_path = public, extensions
as $$
declare
    v_genres      text[];
    v_artists     text[];
    v_avg_bpm     smallint;
    v_hours       smallint[];
    v_taste       vector(768);
    v_play_count  int;
    v_like_count  int;
    v_skip_count  int;
    v_vibe        text;
begin
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

    select avg(t.embedding)::vector(768)
    into v_taste
    from listening_history lh
    join tracks t on t.id = lh.track_id
    where lh.user_id = p_user_id
      and lh.action in ('play', 'like')
      and t.embedding is not null
      and lh.created_at > now() - interval '60 days'
    limit 500;

    select count(*) filter (where action = 'play'),
           count(*) filter (where action = 'like'),
           count(*) filter (where action = 'skip')
    into v_play_count, v_like_count, v_skip_count
    from listening_history
    where user_id = p_user_id;

    v_vibe := case
        when v_avg_bpm > 120 and v_genres && array['electronic','dance','edm'] then 'energetic'
        when v_avg_bpm < 90  and v_genres && array['ambient','classical','jazz','lo-fi'] then 'chill'
        when v_genres && array['rock','metal','punk'] then 'intense'
        when v_genres && array['hip-hop','rap','trap'] then 'urban'
        when v_genres && array['pop','indie'] then 'mainstream'
        else 'mixed'
    end;

    insert into user_profiles (
        user_id, fav_genres, fav_artists, avg_bpm,
        preferred_hours, taste_embedding, play_count,
        like_count, skip_count, fav_vibe, updated_at
    )
    values (
        p_user_id, v_genres, v_artists, v_avg_bpm,
        v_hours, v_taste, v_play_count,
        v_like_count, v_skip_count, v_vibe, now()
    )
    on conflict (user_id) do update set
        fav_genres      = excluded.fav_genres,
        fav_artists     = excluded.fav_artists,
        avg_bpm         = excluded.avg_bpm,
        preferred_hours = excluded.preferred_hours,
        taste_embedding = excluded.taste_embedding,
        play_count      = excluded.play_count,
        like_count      = excluded.like_count,
        skip_count      = excluded.skip_count,
        fav_vibe        = excluded.fav_vibe,
        updated_at      = now();
end;
$$;


-- ── recommend_tracks (main recommendation engine) ───────────────────────────
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
set search_path = public, extensions
as $$
declare
    v_taste      vector(768);
    v_genres     text[];
    v_hours      smallint[];
    v_hour       smallint;
    v_max_dl     double precision;
    v_listened   bigint[];
    v_has_embed  boolean;
begin
    select up.taste_embedding, up.fav_genres, up.preferred_hours
    into v_taste, v_genres, v_hours
    from user_profiles up
    where up.user_id = p_user_id;

    v_hour := extract(hour from now() at time zone 'utc')::smallint;
    v_has_embed := v_taste is not null;

    select array_agg(distinct lh.track_id)
    into v_listened
    from listening_history lh
    where lh.user_id = p_user_id
      and lh.track_id is not null
      and lh.created_at > now() - interval '30 days';

    select max(t.downloads)::double precision into v_max_dl from tracks t;
    if v_max_dl is null or v_max_dl = 0 then v_max_dl := 1; end if;

    if v_has_embed then
        return query
        select
            t.id            as track_id,
            t.source_id,
            t.title,
            t.artist,
            t.genre,
            t.duration,
            t.cover_url,
            t.downloads,
            (
                p_w_embed * coalesce(1.0 - (t.embedding <=> v_taste), 0)
              + p_w_pop   * (t.downloads::double precision / v_max_dl)
              + p_w_fresh * greatest(0::double precision, 1.0 - extract(epoch from now() - t.created_at) / 2592000.0)
              + p_w_genre * case when t.genre = any(v_genres) then 1.0 else 0.0 end
              + p_w_time  * case when v_hour = any(v_hours) then 1.0 else 0.0 end
              + p_w_div   * random()
            )::double precision as final_score,
            coalesce(1.0 - (t.embedding <=> v_taste), 0)::double precision as s_embed,
            (t.downloads::double precision / v_max_dl)::double precision    as s_pop,
            greatest(0::double precision, 1.0 - extract(epoch from now() - t.created_at) / 2592000.0)::double precision as s_fresh,
            (case when t.genre = any(v_genres) then 1.0 else 0.0 end)::double precision as s_genre,
            (case when v_hour = any(v_hours) then 1.0 else 0.0 end)::double precision  as s_time,
            'hybrid_embed'::text as algo
        from tracks t
        where t.embedding is not null
          and t.file_id is not null
          and (v_listened is null or t.id != all(v_listened))
        order by final_score desc
        limit p_limit;
    else
        return query
        select
            t.id            as track_id,
            t.source_id,
            t.title,
            t.artist,
            t.genre,
            t.duration,
            t.cover_url,
            t.downloads,
            (
                p_w_pop   * (t.downloads::double precision / v_max_dl)
              + p_w_fresh * greatest(0::double precision, 1.0 - extract(epoch from now() - t.created_at) / 2592000.0)
              + p_w_genre * case when t.genre = any(v_genres) then 1.0 else 0.0 end
              + p_w_time  * case when v_hour = any(v_hours) then 1.0 else 0.0 end
              + p_w_div   * random()
            )::double precision as final_score,
            0::double precision as s_embed,
            (t.downloads::double precision / v_max_dl)::double precision    as s_pop,
            greatest(0::double precision, 1.0 - extract(epoch from now() - t.created_at) / 2592000.0)::double precision as s_fresh,
            (case when t.genre = any(v_genres) then 1.0 else 0.0 end)::double precision as s_genre,
            (case when v_hour = any(v_hours) then 1.0 else 0.0 end)::double precision  as s_time,
            'popularity'::text as algo
        from tracks t
        where t.file_id is not null
          and (v_listened is null or t.id != all(v_listened))
        order by final_score desc
        limit p_limit;
    end if;
end;
$$;


-- ── similar_tracks (no dimension reference, uses column type) ───────────────
-- No change needed — it uses t.embedding <=> directly, dimension from column type.
