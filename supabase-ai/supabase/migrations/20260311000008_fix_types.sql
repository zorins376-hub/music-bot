-- ═══════════════════════════════════════════════════════════════════════════════
-- Migration 008: Fix type mismatches in scoring functions
--
-- greatest() returns numeric, not double precision. Fix by explicit casts.
-- ═══════════════════════════════════════════════════════════════════════════════

set search_path to public, extensions;

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
    v_taste      vector(1536);
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
      and lh.created_at > now() - interval '90 days';

    if v_listened is null then
        v_listened := '{}';
    end if;

    select coalesce(max(t.downloads), 1)::double precision
    into v_max_dl
    from tracks t
    where t.file_id is not null;

    return query
    with candidates as (
        select t.*
        from tracks t
        where t.file_id is not null
          and t.id != all(v_listened)
          and (
              (v_has_embed and t.embedding is not null)
              or
              (not v_has_embed and t.created_at > now() - interval '30 days')
          )
        order by
            case when v_has_embed and t.embedding is not null
                 then (1.0 - (t.embedding <=> v_taste))::double precision
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

            (case when v_has_embed and c.embedding is not null
                 then greatest(0.0::double precision, (1.0 - (c.embedding <=> v_taste))::double precision)
                 else 0.5::double precision
            end)::double precision as s_embed,

            (c.downloads::double precision / v_max_dl)::double precision as s_pop,

            greatest(0.0::double precision,
                (1.0 - extract(epoch from now() - c.created_at) / (30.0 * 86400))::double precision
            )::double precision as s_fresh,

            (case when c.genre is not null and v_genres is not null
                      and c.genre = any(v_genres)
                 then 1.0
                 else 0.3
            end)::double precision as s_genre,

            (case when v_hours is not null and v_hour = any(v_hours) then 1.0
                 when v_hours is not null and (v_hour + 1)::smallint = any(v_hours) then 0.5
                 when v_hours is not null and (v_hour - 1)::smallint = any(v_hours) then 0.5
                 else 0.0
            end)::double precision as s_time,

            case when v_has_embed then 'hybrid' else 'popular' end as algo

        from candidates c
    ),
    diversified as (
        select
            s.*,
            (p_w_embed * s.s_embed
             + p_w_pop  * s.s_pop
             + p_w_fresh * s.s_fresh
             + p_w_genre * s.s_genre
             + p_w_time  * s.s_time
            )::double precision as final_score,
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
    where d.artist_rank <= 2
    order by d.final_score desc
    limit p_limit;
end;
$$;
