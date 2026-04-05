"""
Last.fm Discovery — genre, geo, chart, artist, personal mix endpoints.
Extracted from webapp/api.py for modularity.
"""
import asyncio
import logging
import random

from fastapi import APIRouter, Depends

from bot.config import settings
from webapp.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["lastfm"])


@router.get("/api/lastfm/tag-top")
async def lastfm_tag_top(
    tag: str = "pop",
    limit: int = 15,
    user: dict = Depends(get_current_user),
):
    """Get top tracks for a genre/mood tag from Last.fm."""
    if not settings.LASTFM_API_KEY:
        return {"tracks": []}
    limit = min(limit, 30)
    try:
        from recommender.lastfm_provider import get_top_by_tag, resolve_to_playable
        raw = await get_top_by_tag(tag, limit=limit + 10)
        if not raw:
            return {"tracks": []}
        resolved = await resolve_to_playable(raw)
        return {"tracks": resolved[:limit], "tag": tag}
    except Exception as e:
        logger.warning("Last.fm tag-top failed: %s", e)
        return {"tracks": []}


@router.get("/api/lastfm/geo-top")
async def lastfm_geo_top(
    country: str = "russia",
    limit: int = 15,
    user: dict = Depends(get_current_user),
):
    """Get trending tracks in a country from Last.fm geo data."""
    if not settings.LASTFM_API_KEY:
        return {"tracks": []}
    limit = min(limit, 30)
    try:
        from recommender.lastfm_provider import get_geo_top_tracks, resolve_to_playable
        raw = await get_geo_top_tracks(country, limit=limit + 10)
        if not raw:
            return {"tracks": []}
        resolved = await resolve_to_playable(raw)
        return {"tracks": resolved[:limit], "country": country}
    except Exception as e:
        logger.warning("Last.fm geo-top failed: %s", e)
        return {"tracks": []}


@router.get("/api/lastfm/chart")
async def lastfm_chart(
    limit: int = 20,
    user: dict = Depends(get_current_user),
):
    """Global Last.fm chart — 20+ years of listening data."""
    if not settings.LASTFM_API_KEY:
        return {"tracks": []}
    limit = min(limit, 30)
    try:
        from recommender.lastfm_provider import get_global_chart, resolve_to_playable
        raw = await get_global_chart(limit=limit + 10)
        if not raw:
            return {"tracks": []}
        resolved = await resolve_to_playable(raw)
        return {"tracks": resolved[:limit]}
    except Exception as e:
        logger.warning("Last.fm chart failed: %s", e)
        return {"tracks": []}


@router.get("/api/lastfm/new-releases")
async def lastfm_new_releases(
    limit: int = 15,
    user: dict = Depends(get_current_user),
):
    """New/top tracks from user's most-listened artists."""
    if not settings.LASTFM_API_KEY:
        return {"tracks": []}
    limit = min(limit, 30)
    uid = int(user.get("id", 0))

    # Get user's top artists from listening history
    fav_artists: list[str] = []
    try:
        from bot.models.base import async_session as _as
        from bot.models.track import ListeningHistory, Track as TrackModel
        from sqlalchemy import select, func, desc
        async with _as() as session:
            top_q = await session.execute(
                select(TrackModel.artist, func.count().label("cnt"))
                .join(ListeningHistory, ListeningHistory.track_id == TrackModel.id)
                .where(ListeningHistory.user_id == uid, ListeningHistory.action == "play")
                .group_by(TrackModel.artist)
                .order_by(desc("cnt"))
                .limit(8)
            )
            fav_artists = [r[0] for r in top_q.all() if r[0]]
    except Exception:
        pass

    if not fav_artists:
        return {"tracks": []}

    try:
        from recommender.lastfm_provider import get_new_from_favorites, resolve_to_playable
        raw = await get_new_from_favorites(fav_artists, limit=limit + 10)
        if not raw:
            return {"tracks": []}
        resolved = await resolve_to_playable(raw)
        return {"tracks": resolved[:limit], "artists": fav_artists[:5]}
    except Exception as e:
        logger.warning("Last.fm new-releases failed: %s", e)
        return {"tracks": []}


@router.get("/api/lastfm/artist-mix")
async def lastfm_artist_mix(
    artist: str = "",
    limit: int = 15,
    user: dict = Depends(get_current_user),
):
    """Discover tracks from artists similar to a given artist."""
    if not settings.LASTFM_API_KEY or not artist:
        return {"tracks": []}
    limit = min(limit, 30)
    try:
        from recommender.lastfm_provider import get_similar_artists_mix, resolve_to_playable
        raw = await get_similar_artists_mix(artist, limit=limit + 10)
        if not raw:
            return {"tracks": []}
        resolved = await resolve_to_playable(raw)
        return {"tracks": resolved[:limit], "seed_artist": artist}
    except Exception as e:
        logger.warning("Last.fm artist-mix failed: %s", e)
        return {"tracks": []}


@router.get("/api/lastfm/tags")
async def lastfm_tags(user: dict = Depends(get_current_user)):
    """Get popular genre tags for the genre picker."""
    if not settings.LASTFM_API_KEY:
        return {"tags": []}
    try:
        from recommender.lastfm_provider import get_top_tags
        tags = await get_top_tags(limit=30)
        return {"tags": tags}
    except Exception as e:
        logger.warning("Last.fm tags failed: %s", e)
        return {"tags": []}


@router.get("/api/lastfm/artist-info")
async def lastfm_artist_info(
    artist: str = "",
    user: dict = Depends(get_current_user),
):
    """Get artist bio, tags, stats, similar artists from Last.fm."""
    if not settings.LASTFM_API_KEY or not artist:
        return {}
    try:
        from recommender.lastfm_provider import get_artist_info
        info = await get_artist_info(artist)
        return info or {}
    except Exception as e:
        logger.warning("Last.fm artist-info failed: %s", e)
        return {}


@router.get("/api/lastfm/personal-mix")
async def lastfm_personal_mix(
    limit: int = 20,
    user: dict = Depends(get_current_user),
):
    """Deep personal mix: takes user's top artists, finds similar tracks via Last.fm,
    and creates a shuffled playlist of discoveries the user hasn't heard."""
    if not settings.LASTFM_API_KEY:
        return {"tracks": []}
    limit = min(limit, 40)
    uid = int(user.get("id", 0))

    # Get user's top artists from history
    fav_artists: list[str] = []
    heard_ids: set[str] = set()
    try:
        from bot.models.base import async_session as _as
        from bot.models.track import ListeningHistory, Track as TrackModel
        from sqlalchemy import select, func, desc
        async with _as() as session:
            top_q = await session.execute(
                select(TrackModel.artist, func.count().label("cnt"))
                .join(ListeningHistory, ListeningHistory.track_id == TrackModel.id)
                .where(ListeningHistory.user_id == uid, ListeningHistory.action == "play")
                .group_by(TrackModel.artist)
                .order_by(desc("cnt"))
                .limit(6)
            )
            fav_artists = [r[0] for r in top_q.all() if r[0]]
            # Get recently heard video_ids to exclude
            recent_q = await session.execute(
                select(TrackModel.video_id)
                .join(ListeningHistory, ListeningHistory.track_id == TrackModel.id)
                .where(ListeningHistory.user_id == uid, ListeningHistory.action == "play")
                .order_by(desc(ListeningHistory.created_at))
                .limit(100)
            )
            heard_ids = {r[0] for r in recent_q.all() if r[0]}
    except Exception:
        pass

    if not fav_artists:
        return {"tracks": []}

    try:
        from recommender.lastfm_provider import (
            get_similar_tracks, get_artist_top_tracks,
            get_similar_artists, resolve_to_playable,
        )

        all_raw: list[dict] = []
        seen: set[str] = set()

        # For each fav artist, get similar artists' top tracks
        sim_tasks = [get_similar_artists(a, limit=3) for a in fav_artists[:4]]
        sim_results = await asyncio.gather(*sim_tasks, return_exceptions=True)

        top_tasks = []
        for r in sim_results:
            if isinstance(r, list):
                for sim_art in r:
                    name = sim_art.get("name", "")
                    if name and name.lower() not in {a.lower() for a in fav_artists}:
                        top_tasks.append(get_artist_top_tracks(name, limit=4))
        top_results = await asyncio.gather(*top_tasks[:12], return_exceptions=True)

        for r in top_results:
            if isinstance(r, list):
                for t in r:
                    key = f"{t['artist'].lower()}:{t['title'].lower()}"
                    if key not in seen:
                        seen.add(key)
                        t["source"] = "lastfm_personal_mix"
                        all_raw.append(t)

        random.shuffle(all_raw)
        resolved = await resolve_to_playable(all_raw[:limit + 10], list(heard_ids))
        return {"tracks": resolved[:limit], "seed_artists": fav_artists[:4]}
    except Exception as e:
        logger.warning("Last.fm personal-mix failed: %s", e)
        return {"tracks": []}


@router.get("/api/lastfm/weekly-discovery")
async def lastfm_weekly_discovery(
    limit: int = 15,
    user: dict = Depends(get_current_user),
):
    """Weekly discovery: mix of global chart, geo top, and genre exploration."""
    if not settings.LASTFM_API_KEY:
        return {"tracks": []}
    limit = min(limit, 30)
    try:
        from recommender.lastfm_provider import (
            get_global_chart, get_geo_top_tracks, get_top_by_tag,
            resolve_to_playable,
        )
        # Fetch from 3 diverse sources in parallel
        chart_t, geo_t, tag_t = await asyncio.gather(
            get_global_chart(limit=10),
            get_geo_top_tracks("russia", limit=10),
            get_top_by_tag(random.choice(["pop", "rock", "electronic", "hip-hop", "indie", "r&b"]), limit=10),
            return_exceptions=True,
        )
        all_raw: list[dict] = []
        seen: set[str] = set()
        for src in [chart_t, geo_t, tag_t]:
            if isinstance(src, list):
                for t in src:
                    key = f"{t.get('artist','').lower()}:{t.get('title','').lower()}"
                    if key not in seen:
                        seen.add(key)
                        all_raw.append(t)
        random.shuffle(all_raw)
        resolved = await resolve_to_playable(all_raw[:limit + 10])
        return {"tracks": resolved[:limit]}
    except Exception as e:
        logger.warning("Last.fm weekly-discovery failed: %s", e)
        return {"tracks": []}
