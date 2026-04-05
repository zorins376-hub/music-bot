"""
Stats & Leaderboard — user statistics, leaderboard, challenges.
Extracted from webapp/api.py for modularity.
"""
import asyncio
import logging

from fastapi import APIRouter, Depends

from webapp.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stats"])


@router.get("/api/stats/{user_id}")
async def user_stats(user_id: int, user: dict = Depends(get_current_user)):
    """Listening statistics for profile page — with hard 4s timeout."""
    _defaults = {
        "total_plays": 0, "total_time": 0, "total_favorites": 0,
        "top_artists": [], "top_genres": [], "recent_tracks": [],
        "xp": 0, "level": 1, "streak_days": 0, "badges": [], "member_since": None,
        "next_streak_milestone": None,
    }

    async def _fetch():
        from bot.models.base import async_session
        from sqlalchemy import select, func
        from bot.models.track import ListeningHistory, Track
        from bot.models.user import User

        result = dict(_defaults)

        async with async_session() as session:
            u = (await session.execute(select(User).where(User.id == user_id))).scalar()

            total_plays = 0
            total_time = 0
            total_favs = 0
            top_artists: list = []
            top_genres: list = []
            recent: list = []

            try:
                total_plays = (await session.execute(
                    select(func.count()).where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play")
                )).scalar() or 0
            except Exception:
                pass

            try:
                total_time = (await session.execute(
                    select(func.coalesce(func.sum(ListeningHistory.listen_duration), 0))
                    .where(ListeningHistory.user_id == user_id)
                )).scalar() or 0
            except Exception:
                pass

            try:
                from bot.models.favorite import FavoriteTrack
                total_favs = (await session.execute(
                    select(func.count()).where(FavoriteTrack.user_id == user_id)
                )).scalar() or 0
            except Exception:
                pass

            try:
                top_artists_q = await session.execute(
                    select(Track.artist, func.count().label("cnt"))
                    .join(ListeningHistory, ListeningHistory.track_id == Track.id)
                    .where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play", Track.artist.isnot(None))
                    .group_by(Track.artist).order_by(func.count().desc()).limit(10)
                )
                top_artists = [{"name": r[0], "count": r[1]} for r in top_artists_q.all()]
            except Exception:
                pass

            try:
                top_genres_q = await session.execute(
                    select(Track.genre, func.count().label("cnt"))
                    .join(ListeningHistory, ListeningHistory.track_id == Track.id)
                    .where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play", Track.genre.isnot(None))
                    .group_by(Track.genre).order_by(func.count().desc()).limit(5)
                )
                top_genres = [{"name": r[0], "count": r[1]} for r in top_genres_q.all()]
            except Exception:
                pass

            try:
                recent_q = await session.execute(
                    select(Track.source_id, Track.title, Track.artist, Track.duration, Track.cover_url, ListeningHistory.created_at)
                    .join(ListeningHistory, ListeningHistory.track_id == Track.id)
                    .where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play")
                    .order_by(ListeningHistory.created_at.desc()).limit(20)
                )
                recent = []
                _rc_to_resolve = []
                for r in recent_q.all():
                    sid = r[0] or ""
                    cover = r[4]
                    if not cover and sid:
                        _rc_to_resolve.append((len(recent), sid, r[1], r[2]))
                    recent.append({
                        "video_id": sid, "title": r[1], "artist": r[2],
                        "duration": r[3] or 0, "duration_fmt": f"{(r[3] or 0) // 60}:{(r[3] or 0) % 60:02d}",
                        "cover_url": cover, "source": "db",
                    })
                if _rc_to_resolve:
                    from webapp.api import _resolve_cover_url
                    async def _res_rc(idx, sid, title, artist):
                        try:
                            url = await _resolve_cover_url(sid, None, title=title, artist=artist)
                            if url: recent[idx]["cover_url"] = url
                        except Exception: pass
                    await asyncio.gather(*[_res_rc(i, s, t, a) for i, s, t, a in _rc_to_resolve[:10]])
            except Exception:
                pass

            streak = u.streak_days if u else 0
            try:
                from bot.services.streak_rewards import get_next_milestone
                next_ms = get_next_milestone(streak)
            except Exception:
                next_ms = None

            return {
                "total_plays": total_plays, "total_time": total_time, "total_favorites": total_favs,
                "top_artists": top_artists, "top_genres": top_genres, "recent_tracks": recent,
                "xp": u.xp if u else 0, "level": u.level if u else 1,
                "streak_days": streak,
                "badges": (u.badges or []) if u else [],
                "member_since": u.created_at.isoformat() if u and u.created_at else None,
                "next_streak_milestone": next_ms,
            }

    try:
        return await asyncio.wait_for(_fetch(), timeout=4.0)
    except asyncio.TimeoutError:
        logger.warning("Stats endpoint timed out for user %s", user_id)
        return _defaults
    except Exception as exc:
        logger.error("Stats endpoint failed for user %s: %s", user_id, exc)
        return _defaults


@router.get("/api/leaderboard/{period}")
async def leaderboard(period: str = "weekly", user: dict = Depends(get_current_user)):
    """Get leaderboard (weekly or alltime). Returns top 50 + user's rank."""
    if period not in ("weekly", "alltime"):
        period = "weekly"
    try:
        from bot.services.leaderboard import get_leaderboard, get_user_rank
        from bot.models.base import async_session
        from bot.models.user import User
        from sqlalchemy import select

        user_id = user.get("id", 0)
        entries = await get_leaderboard(period, limit=50)
        my_rank = await get_user_rank(user_id, period)

        user_ids = [uid for uid, _ in entries[:50]]
        names: dict[int, dict] = {}
        if user_ids:
            async with async_session() as session:
                result = await session.execute(
                    select(User.id, User.first_name, User.username, User.level, User.xp)
                    .where(User.id.in_(user_ids))
                )
                for row in result.all():
                    names[row[0]] = {
                        "name": row[1] or row[2] or str(row[0]),
                        "level": row[3] or 1,
                        "xp": row[4] or 0,
                    }

        board = []
        for rank, (uid, score) in enumerate(entries, 1):
            info = names.get(uid, {"name": str(uid), "level": 1, "xp": 0})
            board.append({
                "rank": rank,
                "user_id": uid,
                "name": info["name"],
                "level": info["level"],
                "xp": info["xp"],
                "score": int(score),
            })

        return {"period": period, "entries": board, "my_rank": my_rank}
    except Exception as exc:
        logger.error("Leaderboard failed: %s", exc)
        return {"period": period, "entries": [], "my_rank": None}
