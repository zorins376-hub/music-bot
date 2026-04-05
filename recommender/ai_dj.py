"""
ai_dj.py — Рекомендательная система «По вашему вкусу» (v3 ML).

Hybrid approach:
  1. ML-based: ALS + Word2Vec embeddings + popularity + freshness (when ML_ENABLED)
  2. Collaborative filtering — SQL-based: find users with similar listening
  3. Content-based — by genre/artist from user profile & history
  4. Fallback — top popular tracks for the week

ML path: 5-component scorer (ALS 40% + Embed 25% + Pop 15% + Fresh 10% + Time 10%)
SQL fallback: 60% collaborative + 40% content-based
Min 50 listens → collaborative, otherwise content-based / fallback.
Redis cache TTL 1h.
"""
import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, and_

from bot.config import config

logger = logging.getLogger(__name__)

# Minimum play count before collaborative/ML filtering activates
_MIN_PLAYS_FOR_COLLAB = 50


async def get_recommendations(
    user_id: int, limit: int = 10, log_for_ab: bool = False
) -> list[dict]:
    """
    Return a list of recommended track dicts (with video_id, title, etc.).
    Uses Redis cache (TTL 1h). Falls back gracefully.
    
    Args:
        user_id: target user
        limit: max results
        log_for_ab: if True, log recommendations to recommendation_log for A/B testing
        
    Returns:
        List of track dicts with additional 'algo' field indicating recommendation source
    """
    from bot.services.cache import cache
    from recommender.config import ml_config

    # Skip cache if A/B logging to ensure fresh algo assignment
    if not log_for_ab:
        cache_key = f"reco:{user_id}"
        try:
            cached = await cache.redis.get(cache_key)
            if cached:
                recs = json.loads(cached)
                return recs[:limit]
        except Exception:
            pass

    recs, algo = await _build_recommendations_with_ab(user_id, limit)

    if recs and not log_for_ab:
        try:
            cache_key = f"reco:{user_id}"
            await cache.redis.setex(cache_key, 3600, json.dumps(recs, ensure_ascii=False))
        except Exception:
            pass

    # Log for A/B testing if enabled
    if log_for_ab and recs and ml_config.ab_test_enabled:
        await _log_recommendations(user_id, recs, algo)

    return recs[:limit]


async def _log_recommendations(user_id: int, recs: list[dict], algo: str) -> None:
    """Log recommendations to recommendation_log for A/B analysis."""
    from bot.models.base import async_session
    from bot.models.recommendation_log import RecommendationLog

    try:
        async with async_session() as session:
            for pos, rec in enumerate(recs):
                # Get track_id from source_id if available
                track_id = rec.get("track_id") or 0
                if not track_id and rec.get("video_id"):
                    # Look up track_id from source_id
                    from bot.models.track import Track
                    result = await session.execute(
                        select(Track.id).where(Track.source_id == rec["video_id"])
                    )
                    row = result.scalar()
                    track_id = row if row else 0

                log_entry = RecommendationLog(
                    user_id=user_id,
                    track_id=track_id,
                    algo=algo,
                    position=pos,
                    score=rec.get("score"),
                )
                session.add(log_entry)
            await session.commit()
    except Exception as e:
        logger.warning("Failed to log recommendations: %s", e)


async def log_recommendation_click(user_id: int, track_id: int | None = None, source_id: str | None = None) -> bool:
    """
    Log that user clicked on a recommended track (for CTR calculation).
    
    Updates the most recent recommendation_log entry for this user+track.
    
    Args:
        user_id: user who clicked
        track_id: database track ID (preferred)
        source_id: track source_id if track_id not available
        
    Returns:
        True if click was logged, False otherwise
    """
    from bot.models.base import async_session
    from bot.models.recommendation_log import RecommendationLog
    from sqlalchemy import update, desc

    if not track_id and not source_id:
        return False

    try:
        async with async_session() as session:
            # Resolve track_id from source_id if needed
            if not track_id and source_id:
                from bot.models.track import Track
                result = await session.execute(
                    select(Track.id).where(Track.source_id == source_id)
                )
                track_id = result.scalar()
                if not track_id:
                    return False

            # Find and update most recent recommendation for this user+track
            # (within last hour to avoid updating old entries)
            from datetime import datetime, timedelta, timezone
            one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
            
            result = await session.execute(
                update(RecommendationLog)
                .where(
                    RecommendationLog.user_id == user_id,
                    RecommendationLog.track_id == track_id,
                    RecommendationLog.clicked == False,
                    RecommendationLog.created_at >= one_hour_ago,
                )
                .values(clicked=True)
            )
            await session.commit()
            return result.rowcount > 0
    except Exception as e:
        logger.warning("Failed to log recommendation click: %s", e)
        return False


async def _build_recommendations_with_ab(user_id: int, limit: int) -> tuple[list[dict], str]:
    """Build recommendations with A/B test routing.
    
    Returns tuple of (recommendations, algo_name).
    """
    from recommender.config import ml_config
    import random
    
    algo = "sql"  # default
    
    # A/B test routing if enabled
    if ml_config.ab_test_enabled and config.ML_ENABLED:
        # Use user_id hash for consistent group assignment
        if user_id % 2 == 0:
            algo = "ml"
        else:
            algo = "sql"
    elif config.ML_ENABLED:
        algo = "ml"

    if config.ML_ENABLED:
        recs = await _build_recommendations(user_id, limit, force_algo=algo)
    else:
        recs = await _build_recommendations(user_id, limit)
    return recs, algo


async def _build_recommendations(
    user_id: int, limit: int, force_algo: str | None = None
) -> list[dict]:
    """Build hybrid recommendations: ML scorer first, SQL fallback.
    
    Args:
        user_id: target user
        limit: max results
        force_algo: if set, force specific algo ("ml" or "sql"). Used for A/B testing.
    """
    from bot.models.base import async_session
    from bot.models.track import ListeningHistory, Track
    from bot.models.user import User

    # ── Try ML-based scoring (if enabled and not forced to SQL) ──────────
    use_ml = (
        config.ML_ENABLED 
        and (force_algo is None or force_algo == "ml")
    )
    
    if use_ml:
        try:
            from recommender.model_store import model_store
            if model_store.is_ready:
                ml_results = await _ml_recommendations(user_id, limit)
                if ml_results:
                    logger.debug("ML reco returned %d tracks for user %d", len(ml_results), user_id)
                    return ml_results
        except Exception as e:
            logger.warning("ML reco failed, falling back to SQL: %s", e)

    # ── SQL fallback ─────────────────────────────────────────────────────
    async with async_session() as session:
        # Count user plays
        play_count_r = await session.execute(
            select(func.count(ListeningHistory.id)).where(
                ListeningHistory.user_id == user_id,
                ListeningHistory.action == "play",
            )
        )
        play_count = play_count_r.scalar() or 0

        # Get user's already-listened track IDs
        listened_r = await session.execute(
            select(ListeningHistory.track_id).where(
                ListeningHistory.user_id == user_id,
                ListeningHistory.action == "play",
                ListeningHistory.track_id.is_not(None),
            )
        )
        listened_ids = {row[0] for row in listened_r.all()}

        # Get user profile for content-based
        user_obj = await session.get(User, user_id)

        collab_tracks: list[dict] = []
        content_tracks: list[dict] = []

        # ── Collaborative filtering ──────────────────────────────
        if play_count >= _MIN_PLAYS_FOR_COLLAB and listened_ids:
            collab_tracks = await _collaborative(session, user_id, listened_ids, limit)

        # ── Content-based filtering ──────────────────────────────
        content_tracks = await _content_based(session, user_obj, listened_ids, limit)

        # ── Cold start boost: trending + Deezer discovery ────────
        if play_count < _MIN_PLAYS_FOR_COLLAB and len(content_tracks) < limit:
            try:
                trending = await _popular_fallback(session, listened_ids, limit)
                # Also try Deezer mood discovery for variety
                from recommender.deezer_discovery import discover_by_mood
                moods = ["pop", "chill", "dance"]
                import random as _rnd
                dz_cold = await discover_by_mood(_rnd.choice(moods), limit=limit // 2)
                # Interleave: content first, then trending, then deezer
                cold_pool = content_tracks + trending + dz_cold
                # Deduplicate
                seen_cs: set[str] = set()
                deduped: list[dict] = []
                for t in cold_pool:
                    sid = t.get("video_id", "")
                    if sid and sid not in seen_cs:
                        seen_cs.add(sid)
                        deduped.append(t)
                return deduped[:limit]
            except Exception:
                pass

        # ── Merge: 60 % collaborative + 40 % content-based ──────
        if collab_tracks and content_tracks:
            n_collab = max(1, int(limit * 0.6))
            n_content = limit - n_collab
            merged = collab_tracks[:n_collab] + content_tracks[:n_content]
        elif collab_tracks:
            merged = collab_tracks[:limit]
        elif content_tracks:
            merged = content_tracks[:limit]
        else:
            # Fallback: popular tracks for the week
            merged = await _popular_fallback(session, listened_ids, limit)

        # Deduplicate by source_id
        seen: set[str] = set()
        result: list[dict] = []
        for t in merged:
            sid = t.get("video_id", "")
            if sid and sid not in seen:
                seen.add(sid)
                result.append(t)
            if len(result) >= limit:
                break

        # Insert sponsored track at position 3-5 if available
        try:
            from bot.services.sponsored_engine import get_sponsored_track
            user_genres = []
            if user_obj and user_obj.fav_genres:
                user_genres = user_obj.fav_genres
            sponsored = await get_sponsored_track(user_id, user_genres=user_genres)
            if sponsored:
                insert_pos = min(3, len(result))
                result.insert(insert_pos, sponsored)
                # Trim to limit
                result = result[:limit]
        except Exception:
            pass

        return result


async def _collaborative(session, user_id: int, listened_ids: set[int], limit: int) -> list[dict]:
    """Find similar users and recommend their tracks."""
    from bot.models.track import ListeningHistory, Track

    # Find users who share ≥3 tracks with current user (limit to 50 similar users)
    similar_users_r = await session.execute(
        select(ListeningHistory.user_id, func.count(ListeningHistory.track_id).label("shared"))
        .where(
            ListeningHistory.action == "play",
            ListeningHistory.track_id.in_(listened_ids),
            ListeningHistory.user_id != user_id,
        )
        .group_by(ListeningHistory.user_id)
        .having(func.count(ListeningHistory.track_id) >= 3)
        .order_by(func.count(ListeningHistory.track_id).desc())
        .limit(50)
    )
    similar_user_ids = [row[0] for row in similar_users_r.all()]

    if not similar_user_ids:
        return []

    # Get tracks that similar users played but current user hasn't, ranked by frequency
    reco_r = await session.execute(
        select(
            Track,
            func.count(ListeningHistory.id).label("freq"),
        )
        .join(ListeningHistory, ListeningHistory.track_id == Track.id)
        .where(
            ListeningHistory.user_id.in_(similar_user_ids),
            ListeningHistory.action == "play",
            ~Track.id.in_(listened_ids),
            Track.file_id.is_not(None),
        )
        .group_by(Track.id)
        .order_by(func.count(ListeningHistory.id).desc())
        .limit(limit * 2)
    )
    return [_track_to_dict(row[0]) for row in reco_r.all()]


async def _content_based(session, user_obj, listened_ids: set[int], limit: int) -> list[dict]:
    """Recommend tracks by matching genre/artist from user profile."""
    from bot.models.track import Track

    conditions = []
    if user_obj and user_obj.fav_genres:
        conditions.append(Track.genre.in_(user_obj.fav_genres))
    if user_obj and user_obj.fav_artists:
        for artist in user_obj.fav_artists[:3]:
            conditions.append(Track.artist.ilike(f"%{artist}%"))

    if not conditions:
        # Fall back to genres from listening history
        from bot.models.track import ListeningHistory
        genre_r = await session.execute(
            select(Track.genre, func.count().label("cnt"))
            .join(ListeningHistory, ListeningHistory.track_id == Track.id)
            .where(
                ListeningHistory.user_id == user_obj.id if user_obj else 0,
                ListeningHistory.action == "play",
                Track.genre.is_not(None),
            )
            .group_by(Track.genre)
            .order_by(func.count().desc())
            .limit(3)
        )
        top_genres = [row[0] for row in genre_r.all()]
        if top_genres:
            conditions.append(Track.genre.in_(top_genres))

    if not conditions:
        return []

    from sqlalchemy import or_
    q = (
        select(Track)
        .where(
            or_(*conditions),
            Track.file_id.is_not(None),
        )
        .order_by(Track.downloads.desc())
        .limit(limit * 2)
    )
    if listened_ids:
        q = q.where(~Track.id.in_(listened_ids))

    result = await session.execute(q)
    return [_track_to_dict(t) for t in result.scalars().all()]


async def _popular_fallback(session, listened_ids: set[int], limit: int) -> list[dict]:
    """Top popular tracks from the last week."""
    from bot.models.track import ListeningHistory, Track

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    q = (
        select(Track, func.count(ListeningHistory.id).label("cnt"))
        .join(ListeningHistory, ListeningHistory.track_id == Track.id)
        .where(
            ListeningHistory.action == "play",
            ListeningHistory.created_at >= week_ago,
            Track.file_id.is_not(None),
        )
        .group_by(Track.id)
        .order_by(func.count(ListeningHistory.id).desc())
        .limit(limit * 2)
    )
    if listened_ids:
        q = q.where(~Track.id.in_(listened_ids))

    result = await session.execute(q)
    rows = result.all()
    if rows:
        return [_track_to_dict(row[0]) for row in rows]

    # Ultimate fallback: any popular tracks
    result2 = await session.execute(
        select(Track)
        .where(Track.file_id.is_not(None))
        .order_by(Track.downloads.desc())
        .limit(limit)
    )
    return [_track_to_dict(t) for t in result2.scalars().all()]


def _track_to_dict(track) -> dict:
    """Convert a Track model to the dict format used by search results."""
    from bot.utils import fmt_duration
    duration = track.duration if track.duration is not None else 0
    return {
        "video_id": track.source_id,
        "title": track.title or "Unknown",
        "uploader": track.artist or "Unknown",
        "duration": duration,
        "duration_fmt": (fmt_duration(duration) if duration > 0 else "?:??"),
        "source": track.source or "youtube",
        "file_id": track.file_id,
    }


async def update_user_profile(user_id: int) -> None:
    """
    Пересчитывает fav_genres и avg_bpm на основе истории.
    Запускать через cron / после каждых N прослушиваний.
    """
    from sqlalchemy import func, select

    from bot.models.base import async_session
    from bot.models.track import ListeningHistory, Track
    from bot.models.user import User
    from sqlalchemy import update

    async with async_session() as session:
        # Средний BPM последних 50 треков
        result = await session.execute(
            select(func.avg(Track.bpm))
            .join(ListeningHistory, ListeningHistory.track_id == Track.id)
            .where(
                ListeningHistory.user_id == user_id,
                ListeningHistory.action == "play",
                Track.bpm.is_not(None),
            )
            .limit(50)
        )
        avg_bpm = result.scalar()

        # Топ жанры
        genre_result = await session.execute(
            select(Track.genre, func.count().label("cnt"))
            .join(ListeningHistory, ListeningHistory.track_id == Track.id)
            .where(
                ListeningHistory.user_id == user_id,
                ListeningHistory.action == "play",
                Track.genre.is_not(None),
            )
            .group_by(Track.genre)
            .order_by(func.count().desc())
            .limit(3)
        )
        genres = [row[0] for row in genre_result.all()]

        if avg_bpm or genres:
            await session.execute(
                update(User)
                .where(User.id == user_id)
                .values(
                    avg_bpm=int(avg_bpm) if avg_bpm else None,
                    fav_genres=genres if genres else None,
                )
            )
            await session.commit()


async def _ml_recommendations(user_id: int, limit: int) -> list[dict]:
    """Score tracks using ML HybridScorer (ALS + embeddings + popularity + freshness + time)."""
    from bot.models.base import async_session
    from bot.models.track import ListeningHistory, Track
    from bot.models.user import User
    from recommender.scorer import HybridScorer, ScoringContext

    async with async_session() as session:
        # Get user + profile
        user_obj = await session.get(User, user_id)
        preferred_hours = None
        if user_obj and hasattr(user_obj, "preferred_hours"):
            preferred_hours = user_obj.preferred_hours

        # Get user's listened history with source_ids (recent 50 for context, all for exclusion)
        listened_r = await session.execute(
            select(
                ListeningHistory.track_id,
                Track.source_id,
                ListeningHistory.created_at,
            )
            .join(Track, Track.id == ListeningHistory.track_id)
            .where(
                ListeningHistory.user_id == user_id,
                ListeningHistory.action == "play",
                ListeningHistory.track_id.is_not(None),
            )
            .order_by(ListeningHistory.created_at.desc())
        )
        history = listened_r.all()
        listened_ids = {row[0] for row in history}
        # Extract source_ids for embedding lookup (most recent first)
        recent_source_ids = [row[1] for row in history[:50] if row[1]]

        if len(listened_ids) < _MIN_PLAYS_FOR_COLLAB:
            return []

        # Get negative feedback (skips/dislikes in last 30 days)
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        skip_r = await session.execute(
            select(ListeningHistory.track_id)
            .where(
                ListeningHistory.user_id == user_id,
                ListeningHistory.action == "skip",
                ListeningHistory.track_id.is_not(None),
                ListeningHistory.created_at >= thirty_days_ago,
            )
        )
        skip_ids = {row[0] for row in skip_r.all()}

        dislike_r = await session.execute(
            select(ListeningHistory.track_id)
            .where(
                ListeningHistory.user_id == user_id,
                ListeningHistory.action == "dislike",
                ListeningHistory.track_id.is_not(None),
            )
        )
        dislike_ids = {row[0] for row in dislike_r.all()}

        # Get candidate pool: all tracks with file_id, include metadata
        candidates_r = await session.execute(
            select(
                Track.id,
                Track.source_id,
                Track.artist,
                Track.genre,
                Track.downloads,  # as proxy for play_count
                Track.created_at,
            )
            .where(Track.file_id.is_not(None))
            .limit(10000)
        )
        candidates = candidates_r.all()
        
        # Build candidate dicts for scorer
        candidate_dicts = [
            {
                "id": r[0],
                "source_id": r[1] or "",
                "artist": r[2] or "",
                "genre": r[3] or "",
                "play_count": r[4] or 0,
                "added_at": r[5],
            }
            for r in candidates
        ]

        # Build scoring context with source_ids for embeddings
        ctx = ScoringContext(
            current_hour_utc=datetime.now(timezone.utc).hour,
            recent_source_ids=recent_source_ids,
            listened_ids=listened_ids,
            preferred_hours=preferred_hours,
            skip_track_ids=skip_ids,
            dislike_track_ids=dislike_ids,
        )

        # Score with HybridScorer
        scorer = HybridScorer()
        scored = scorer.score(user_id, candidate_dicts, ctx)
        filtered = scorer.apply_diversity(scored, limit=limit * 2)

        if not filtered:
            return []

        # ── Serendipity mix: replace ~20% with exploration picks ─────
        import random as _rnd
        n_serendipity = max(1, limit // 5)
        # Get user's familiar artists/genres
        familiar_artists = {r[2].lower() for r in candidates[:100] if r[2]} & {
            row[1].lower() if row[1] else "" for row in history[:100]
        }
        # Pick from scored tracks ranked 10-40 that are NOT from familiar artists
        exploration_pool = [
            t for t in scored[10:40]
            if t.artist.lower() not in familiar_artists and t.score > 0
        ]
        if exploration_pool:
            picks = _rnd.sample(exploration_pool, min(n_serendipity, len(exploration_pool)))
            # Replace last N items of filtered with exploration picks
            filtered = filtered[:limit * 2 - len(picks)] + picks

        # Load full track objects for result
        ranked_ids = [t.track_id for t in filtered]
        tracks_r = await session.execute(
            select(Track).where(Track.id.in_(ranked_ids))
        )
        track_map = {t.id: t for t in tracks_r.scalars().all()}

        return [_track_to_dict(track_map[tid]) for tid in ranked_ids if tid in track_map][:limit]


async def get_similar_tracks(track_id: int, limit: int = 10) -> list[dict]:
    """
    Get tracks similar to a given track using embeddings.
    
    Used by mini app "Similar Tracks" feature.
    
    Args:
        track_id: source track ID (database ID)
        limit: max results
        
    Returns:
        List of similar track dicts
    """
    from bot.models.base import async_session
    from bot.models.track import Track
    from bot.services.cache import cache

    # Check cache first
    cache_key = f"similar:{track_id}"
    try:
        cached = await cache.redis.get(cache_key)
        if cached:
            return json.loads(cached)[:limit]
    except Exception:
        pass

    result: list[dict] = []

    # Get source track to find its source_id
    async with async_session() as session:
        source_track = await session.get(Track, track_id)
        if not source_track:
            return []
        
        source_id = source_track.source_id

    # ── Try ML embeddings first ──────────────────────────────────────────
    if config.ML_ENABLED and source_id:
        try:
            from recommender.embeddings import TrackEmbeddings
            embeddings = TrackEmbeddings()
            
            # get_similar_tracks returns [(source_id, score), ...]
            similar_pairs = embeddings.get_similar_tracks(source_id, topn=limit * 2)
            
            if similar_pairs:
                similar_source_ids = [sid for sid, score in similar_pairs]
                async with async_session() as session:
                    tracks_r = await session.execute(
                        select(Track).where(Track.source_id.in_(similar_source_ids))
                    )
                    track_map = {t.source_id: t for t in tracks_r.scalars().all()}
                    # Maintain similarity order
                    result = [
                        _track_to_dict(track_map[sid]) 
                        for sid in similar_source_ids 
                        if sid in track_map
                    ]
        except Exception as e:
            logger.warning("ML similar tracks failed: %s", e)

    # ── SQL fallback: same artist/genre ──────────────────────────────────
    if not result:
        async with async_session() as session:
            source_track = await session.get(Track, track_id)
            if not source_track:
                return []

            conditions = []
            if source_track.artist:
                conditions.append(Track.artist.ilike(f"%{source_track.artist}%"))
            if source_track.genre:
                conditions.append(Track.genre == source_track.genre)

            if conditions:
                from sqlalchemy import or_
                tracks_r = await session.execute(
                    select(Track)
                    .where(
                        or_(*conditions),
                        Track.id != track_id,
                        Track.file_id.is_not(None),
                    )
                    .order_by(Track.downloads.desc())
                    .limit(limit)
                )
                result = [_track_to_dict(t) for t in tracks_r.scalars().all()]

    # Cache result
    if result:
        try:
            await cache.redis.setex(cache_key, 3600, json.dumps(result, ensure_ascii=False))
        except Exception:
            pass

    return result[:limit]
