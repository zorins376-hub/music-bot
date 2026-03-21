import json
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

from sqlalchemy import func, select

from bot.models.base import async_session
from bot.models.daily_mix import DailyMix, DailyMixTrack
from bot.models.favorite import FavoriteTrack
from bot.models.track import ListeningHistory, Track
from bot.services.cache import cache
from bot.utils import fmt_duration


def _track_to_result(track: Track) -> dict:
    return {
        "video_id": track.source_id,
        "title": track.title or "Unknown",
        "uploader": track.artist or "Unknown",
        "duration": int(track.duration) if track.duration else None,
        "duration_fmt": fmt_duration(track.duration or 0),
        "source": track.source or "channel",
    }


async def get_or_build_daily_mix(user_id: int, limit: int = 25) -> list[dict]:
    """Return cached daily mix or build a new one for today."""
    today_date = datetime.now(timezone.utc).date()
    today = today_date.isoformat()
    key = f"daily_mix:{user_id}:{today}"

    try:
        cached = await cache.redis.get(key)
        if cached:
            data = json.loads(cached)
            if isinstance(data, list) and data:
                return data[:limit]
    except Exception:
        logger.debug("daily_mix cache get failed user=%s", user_id, exc_info=True)

    tracks = await _load_daily_mix_from_db(user_id, today_date, limit=limit)
    if not tracks:
        built_tracks = await _build_daily_mix_tracks(user_id, limit=limit)
        await _save_daily_mix_to_db(user_id, today_date, built_tracks)
        tracks = [_track_to_result(track) for track in built_tracks[:limit]]

    try:
        now = datetime.now(timezone.utc)
        next_day = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        ttl = max(60, int((next_day - now).total_seconds()))
        await cache.redis.setex(key, ttl, json.dumps(tracks, ensure_ascii=False))
    except Exception:
        logger.debug("daily_mix cache set failed user=%s", user_id, exc_info=True)

    return tracks


async def _build_daily_mix_tracks(user_id: int, limit: int = 25) -> list[Track]:
    """Build daily mix from favorites, recent artists and popular tracks."""
    async with async_session() as session:
        fav_r = await session.execute(
            select(Track)
            .join(FavoriteTrack, FavoriteTrack.track_id == Track.id)
            .where(FavoriteTrack.user_id == user_id)
            .order_by(FavoriteTrack.created_at.desc())
            .limit(20)
        )
        fav_tracks = list(fav_r.scalars().all())

        artist_r = await session.execute(
            select(Track.artist, func.count(ListeningHistory.id).label("cnt"))
            .join(ListeningHistory, ListeningHistory.track_id == Track.id)
            .where(
                ListeningHistory.user_id == user_id,
                ListeningHistory.action == "play",
                Track.artist.is_not(None),
            )
            .group_by(Track.artist)
            .order_by(func.count(ListeningHistory.id).desc())
            .limit(5)
        )
        top_artists = [row[0] for row in artist_r.all() if row[0]]

        artist_tracks: list[Track] = []
        if top_artists:
            art_r = await session.execute(
                select(Track)
                .where(Track.artist.in_(top_artists))
                .order_by(Track.downloads.desc())
                .limit(40)
            )
            artist_tracks = list(art_r.scalars().all())

        pop_r = await session.execute(
            select(Track)
            .order_by(Track.downloads.desc())
            .limit(80)
        )
        popular_tracks = list(pop_r.scalars().all())

    merged = []
    seen_ids: set[int] = set()
    for source in (fav_tracks, artist_tracks, popular_tracks):
        for track in source:
            if track.id in seen_ids:
                continue
            seen_ids.add(track.id)
            merged.append(track)
            if len(merged) >= limit:
                break
        if len(merged) >= limit:
            break

    return merged[:limit]


async def _load_daily_mix_from_db(user_id: int, mix_date, limit: int = 25) -> list[dict]:
    async with async_session() as session:
        mix_r = await session.execute(
            select(DailyMix)
            .where(DailyMix.user_id == user_id, DailyMix.mix_date == mix_date)
            .limit(1)
        )
        mix = mix_r.scalar_one_or_none()
        if mix is None:
            return []

        tracks_r = await session.execute(
            select(Track)
            .join(DailyMixTrack, DailyMixTrack.track_id == Track.id)
            .where(DailyMixTrack.mix_id == mix.id)
            .order_by(DailyMixTrack.position.asc())
            .limit(limit)
        )
        tracks = list(tracks_r.scalars().all())

    return [_track_to_result(track) for track in tracks]


async def _save_daily_mix_to_db(user_id: int, mix_date, tracks: list[Track]) -> None:
    if not tracks:
        return

    async with async_session() as session:
        existing_r = await session.execute(
            select(DailyMix)
            .where(DailyMix.user_id == user_id, DailyMix.mix_date == mix_date)
            .limit(1)
        )
        existing = existing_r.scalar_one_or_none()
        if existing is not None:
            return

        mix = DailyMix(user_id=user_id, mix_date=mix_date, title="Daily Mix", source="daily_mix")
        session.add(mix)
        await session.flush()

        for pos, track in enumerate(tracks):
            session.add(
                DailyMixTrack(
                    mix_id=mix.id,
                    track_id=track.id,
                    position=pos,
                )
            )

        await session.commit()
