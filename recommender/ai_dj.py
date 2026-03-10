"""
ai_dj.py — Рекомендательная система «По вашему вкусу» (v2).

Hybrid approach:
  1. Collaborative filtering — SQL-based: find users with similar listening,
     recommend tracks they played but current user hasn't.
  2. Content-based — by genre/artist from user profile & history.
  3. Fallback — top popular tracks for the week.

60 % collaborative + 40 % content-based (when both available).
Min 50 listens → collaborative, otherwise content-based / fallback.
Redis cache TTL 1 h.
"""
import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, and_

logger = logging.getLogger(__name__)

# Minimum play count before collaborative filtering activates
_MIN_PLAYS_FOR_COLLAB = 50


async def get_recommendations(user_id: int, limit: int = 10) -> list[dict]:
    """
    Return a list of recommended track dicts (with video_id, title, etc.).
    Uses Redis cache (TTL 1h). Falls back gracefully.
    """
    from bot.services.cache import cache

    cache_key = f"reco:{user_id}"
    try:
        cached = await cache.redis.get(cache_key)
        if cached:
            recs = json.loads(cached)
            return recs[:limit]
    except Exception:
        pass

    recs = await _build_recommendations(user_id, limit)

    if recs:
        try:
            await cache.redis.setex(cache_key, 3600, json.dumps(recs, ensure_ascii=False))
        except Exception:
            pass

    return recs[:limit]


async def _build_recommendations(user_id: int, limit: int) -> list[dict]:
    """Build hybrid recommendations from DB."""
    from bot.models.base import async_session
    from bot.models.track import ListeningHistory, Track
    from bot.models.user import User

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
    return {
        "video_id": track.source_id,
        "title": track.title or "Unknown",
        "uploader": track.artist or "Unknown",
        "duration": track.duration or 0,
        "duration_fmt": fmt_duration(track.duration),
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
