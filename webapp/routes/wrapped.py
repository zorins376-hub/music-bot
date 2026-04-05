"""
Wrapped / Music Recap — personalized listening recap like Spotify Wrapped.
Extracted from webapp/api.py for modularity.
"""
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from webapp.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["wrapped"])


@router.get("/api/wrapped")
async def get_wrapped(user: dict = Depends(get_current_user)):
    """
    Personalized music recap — like Spotify Wrapped but available anytime.
    Returns top artists, genres, moods, listening stats, favorite tracks, etc.
    """
    user_id = user.get("id", 0)

    async def _build():
        from bot.models.base import async_session as _as
        from bot.models.track import ListeningHistory, Track as TrackModel
        from bot.models.user import User
        from bot.models.favorite import FavoriteTrack
        from sqlalchemy import select, func, extract

        async with _as() as session:
            u = (await session.execute(select(User).where(User.id == user_id))).scalar()
            if not u:
                raise HTTPException(status_code=404, detail="User not found")

            total_plays = (await session.execute(
                select(func.count()).where(
                    ListeningHistory.user_id == user_id,
                    ListeningHistory.action == "play",
                )
            )).scalar() or 0

            total_time = (await session.execute(
                select(func.coalesce(func.sum(ListeningHistory.listen_duration), 0))
                .where(ListeningHistory.user_id == user_id)
            )).scalar() or 0

            total_favs = (await session.execute(
                select(func.count()).where(FavoriteTrack.user_id == user_id)
            )).scalar() or 0

            top_artists_q = await session.execute(
                select(TrackModel.artist, func.count().label("cnt"))
                .join(ListeningHistory, ListeningHistory.track_id == TrackModel.id)
                .where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play", TrackModel.artist.isnot(None))
                .group_by(TrackModel.artist).order_by(func.count().desc()).limit(10)
            )
            top_artists = [{"name": r[0], "count": r[1]} for r in top_artists_q.all()]

            top_genres_q = await session.execute(
                select(TrackModel.genre, func.count().label("cnt"))
                .join(ListeningHistory, ListeningHistory.track_id == TrackModel.id)
                .where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play", TrackModel.genre.isnot(None))
                .group_by(TrackModel.genre).order_by(func.count().desc()).limit(5)
            )
            top_genres = [{"name": r[0], "count": r[1]} for r in top_genres_q.all()]

            top_track_q = await session.execute(
                select(TrackModel.source_id, TrackModel.title, TrackModel.artist, TrackModel.cover_url, func.count().label("cnt"))
                .join(ListeningHistory, ListeningHistory.track_id == TrackModel.id)
                .where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play")
                .group_by(TrackModel.source_id, TrackModel.title, TrackModel.artist, TrackModel.cover_url)
                .order_by(func.count().desc()).limit(1)
            )
            top_track_row = top_track_q.first()
            top_track = None
            if top_track_row:
                top_track = {
                    "video_id": top_track_row[0], "title": top_track_row[1],
                    "artist": top_track_row[2], "cover_url": top_track_row[3],
                    "play_count": top_track_row[4],
                }

            top_tracks_q = await session.execute(
                select(TrackModel.source_id, TrackModel.title, TrackModel.artist, TrackModel.cover_url, TrackModel.duration, func.count().label("cnt"))
                .join(ListeningHistory, ListeningHistory.track_id == TrackModel.id)
                .where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play")
                .group_by(TrackModel.source_id, TrackModel.title, TrackModel.artist, TrackModel.cover_url, TrackModel.duration)
                .order_by(func.count().desc()).limit(10)
            )
            top_tracks = []
            _tt_to_resolve = []
            for r in top_tracks_q.all():
                sid = r[0] or ""
                cover = r[3]
                if not cover and sid:
                    _tt_to_resolve.append((len(top_tracks), sid, r[1], r[2]))
                top_tracks.append({
                    "video_id": sid, "title": r[1], "artist": r[2], "cover_url": cover,
                    "duration": r[4] or 0, "duration_fmt": f"{(r[4] or 0)//60}:{(r[4] or 0)%60:02d}",
                    "play_count": r[5], "source": "db",
                })
            if _tt_to_resolve:
                from webapp.api import _resolve_cover_url
                async def _res_tt(idx, sid, title, artist):
                    try:
                        url = await _resolve_cover_url(sid, None, title=title, artist=artist)
                        if url: top_tracks[idx]["cover_url"] = url
                    except Exception: pass
                await asyncio.gather(*[_res_tt(i, s, t, a) for i, s, t, a in _tt_to_resolve[:10]])

            hours_q = await session.execute(
                select(
                    extract("hour", ListeningHistory.created_at).label("hr"),
                    func.count(),
                )
                .where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play")
                .group_by("hr")
            )
            hours_map = {int(r[0]): r[1] for r in hours_q.all()}
            listening_hours = [hours_map.get(h, 0) for h in range(24)]
            peak_hour = max(range(24), key=lambda h: listening_hours[h]) if total_plays > 0 else 12

            unique_artists = (await session.execute(
                select(func.count(func.distinct(TrackModel.artist)))
                .join(ListeningHistory, ListeningHistory.track_id == TrackModel.id)
                .where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play")
            )).scalar() or 0

            unique_tracks = (await session.execute(
                select(func.count(func.distinct(TrackModel.id)))
                .join(ListeningHistory, ListeningHistory.track_id == TrackModel.id)
                .where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play")
            )).scalar() or 0

            personality = "Explorer"
            if top_artists and top_artists[0]["count"] > total_plays * 0.3:
                personality = "Loyalist"
            elif unique_artists > 50:
                personality = "Explorer"
            elif len(top_genres) >= 4:
                personality = "Eclectic"
            elif total_time > 36000:
                personality = "Marathon Runner"
            elif peak_hour >= 22 or peak_hour <= 4:
                personality = "Night Owl"

            return {
                "total_plays": total_plays,
                "total_time": total_time,
                "total_favorites": total_favs,
                "unique_artists": unique_artists,
                "unique_tracks": unique_tracks,
                "top_artists": top_artists,
                "top_genres": top_genres,
                "top_track": top_track,
                "top_tracks": top_tracks,
                "listening_hours": listening_hours,
                "peak_hour": peak_hour,
                "personality": personality,
                "level": u.level if u else 1,
                "xp": u.xp if u else 0,
                "streak_days": u.streak_days if u else 0,
                "member_since": u.created_at.isoformat() if u and u.created_at else None,
            }

    try:
        return await asyncio.wait_for(_build(), timeout=8.0)
    except asyncio.TimeoutError:
        return JSONResponse(
            status_code=504,
            content={"detail": "timeout", "error": "timeout", "total_plays": 0},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Wrapped failed: %s", e)
        return JSONResponse(
            status_code=500,
            content={"detail": "Wrapped build failed", "error": str(e), "total_plays": 0},
        )
