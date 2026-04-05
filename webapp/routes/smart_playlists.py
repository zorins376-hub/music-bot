"""
Smart Playlists — auto-generated playlists based on user data.
Extracted from webapp/api.py for modularity.
"""
import asyncio
import logging

from fastapi import APIRouter, Depends

from webapp.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["smart-playlists"])


@router.get("/api/smart-playlists")
async def smart_playlists(user: dict = Depends(get_current_user)):
    """
    Auto-generated smart playlists based on user listening data.
    Returns playlist definitions, each with tracks.
    """
    user_id = user.get("id", 0)

    async def _build():
        from bot.models.base import async_session as _as
        from bot.models.track import ListeningHistory, Track as TrackModel
        from bot.models.favorite import FavoriteTrack
        from sqlalchemy import select, func, desc
        from datetime import datetime, timezone, timedelta

        now = datetime.now(timezone.utc)
        playlists = []

        async with _as() as session:
            # 1) Most Played (all time top 20)
            try:
                top_q = await session.execute(
                    select(
                        TrackModel.source_id, TrackModel.title, TrackModel.artist,
                        TrackModel.duration, TrackModel.cover_url,
                        func.count().label("cnt"),
                    )
                    .join(ListeningHistory, ListeningHistory.track_id == TrackModel.id)
                    .where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play")
                    .group_by(TrackModel.source_id, TrackModel.title, TrackModel.artist, TrackModel.duration, TrackModel.cover_url)
                    .order_by(desc("cnt")).limit(20)
                )
                tracks = [{
                    "video_id": r[0], "title": r[1], "artist": r[2],
                    "duration": r[3] or 0,
                    "duration_fmt": f"{(r[3] or 0)//60}:{(r[3] or 0)%60:02d}",
                    "source": "db", "cover_url": r[4],
                } for r in top_q.all()]
                if tracks:
                    playlists.append({
                        "id": "most_played", "name": "Most Played",
                        "icon": "fire", "description": "Your all-time favorites",
                        "tracks": tracks,
                    })
            except Exception:
                pass

            # 2) Recently Discovered (first listen in last 7 days)
            try:
                week_ago = now - timedelta(days=7)
                recent_q = await session.execute(
                    select(
                        TrackModel.source_id, TrackModel.title, TrackModel.artist,
                        TrackModel.duration, TrackModel.cover_url,
                        func.min(ListeningHistory.created_at).label("first_listen"),
                    )
                    .join(ListeningHistory, ListeningHistory.track_id == TrackModel.id)
                    .where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play")
                    .group_by(TrackModel.source_id, TrackModel.title, TrackModel.artist, TrackModel.duration, TrackModel.cover_url)
                    .having(func.min(ListeningHistory.created_at) >= week_ago)
                    .order_by(desc("first_listen")).limit(20)
                )
                tracks = [{
                    "video_id": r[0], "title": r[1], "artist": r[2],
                    "duration": r[3] or 0,
                    "duration_fmt": f"{(r[3] or 0)//60}:{(r[3] or 0)%60:02d}",
                    "source": "db", "cover_url": r[4],
                } for r in recent_q.all()]
                if tracks:
                    playlists.append({
                        "id": "recently_discovered", "name": "Recently Discovered",
                        "icon": "discover", "description": "New tracks from this week",
                        "tracks": tracks,
                    })
            except Exception:
                pass

            # 3) Favorites Mix (shuffled favorites)
            try:
                favs_q = await session.execute(
                    select(
                        TrackModel.source_id, TrackModel.title, TrackModel.artist,
                        TrackModel.duration, TrackModel.cover_url,
                    )
                    .join(FavoriteTrack, FavoriteTrack.track_id == TrackModel.id)
                    .where(FavoriteTrack.user_id == user_id)
                    .order_by(func.random()).limit(25)
                )
                tracks = [{
                    "video_id": r[0], "title": r[1], "artist": r[2],
                    "duration": r[3] or 0,
                    "duration_fmt": f"{(r[3] or 0)//60}:{(r[3] or 0)%60:02d}",
                    "source": "db", "cover_url": r[4],
                } for r in favs_q.all()]
                if tracks:
                    playlists.append({
                        "id": "favorites_mix", "name": "Favorites Mix",
                        "icon": "heart", "description": "Your liked tracks shuffled",
                        "tracks": tracks,
                    })
            except Exception:
                pass

            # 4) Late Night (tracks played after 10pm)
            try:
                from sqlalchemy import extract
                night_q = await session.execute(
                    select(
                        TrackModel.source_id, TrackModel.title, TrackModel.artist,
                        TrackModel.duration, TrackModel.cover_url,
                        func.count().label("cnt"),
                    )
                    .join(ListeningHistory, ListeningHistory.track_id == TrackModel.id)
                    .where(
                        ListeningHistory.user_id == user_id,
                        ListeningHistory.action == "play",
                        extract("hour", ListeningHistory.created_at).in_([22, 23, 0, 1, 2, 3]),
                    )
                    .group_by(TrackModel.source_id, TrackModel.title, TrackModel.artist, TrackModel.duration, TrackModel.cover_url)
                    .order_by(desc("cnt")).limit(20)
                )
                tracks = [{
                    "video_id": r[0], "title": r[1], "artist": r[2],
                    "duration": r[3] or 0,
                    "duration_fmt": f"{(r[3] or 0)//60}:{(r[3] or 0)%60:02d}",
                    "source": "db", "cover_url": r[4],
                } for r in night_q.all()]
                if tracks:
                    playlists.append({
                        "id": "late_night", "name": "Late Night",
                        "icon": "moon", "description": "What you listen to after dark",
                        "tracks": tracks,
                    })
            except Exception:
                pass

        return {"playlists": playlists}

    try:
        return await asyncio.wait_for(_build(), timeout=6.0)
    except asyncio.TimeoutError:
        return {"playlists": []}
    except Exception as e:
        logger.error("Smart playlists failed: %s", e)
        return {"playlists": []}
