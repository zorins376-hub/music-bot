"""
Last.fm powered music discovery — the gold standard for similar tracks.

Uses free Last.fm API (key required, no auth):
  - track.getSimilar  → tracks similar by listening patterns (20+ years of data)
  - artist.getSimilar  → artists with similar listener base
  - track.getTopTags   → genre/mood tags for energy matching

This gives dramatically better recommendations than metadata-only approaches
because it's based on real listening behavior of millions of users.

API key: free at https://www.last.fm/api/account/create
Rate limit: 5 req/sec
"""
import asyncio
import logging
import time
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

_LASTFM_API = "https://ws.audioscrobbler.com/2.0/"

# ── In-memory cache ──
_cache: dict[str, tuple[float, any]] = {}
_CACHE_TTL = 3600  # 1 hour
_CACHE_MAX = 500


def _cache_get(key: str):
    if key in _cache:
        ts, val = _cache[key]
        if time.time() - ts < _CACHE_TTL:
            return val
        del _cache[key]
    return None


def _cache_set(key: str, val):
    if len(_cache) >= _CACHE_MAX:
        oldest = min(_cache, key=lambda k: _cache[k][0])
        del _cache[oldest]
    _cache[key] = (time.time(), val)


def _get_api_key() -> Optional[str]:
    try:
        from bot.config import settings
        return settings.LASTFM_API_KEY
    except Exception:
        return None


async def _lastfm_get(method: str, params: dict) -> Optional[dict]:
    """Make a GET request to Last.fm API."""
    api_key = _get_api_key()
    if not api_key:
        return None

    params = {
        "method": method,
        "api_key": api_key,
        "format": "json",
        **params,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                _LASTFM_API, params=params, timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status != 200:
                    logger.warning("Last.fm %s returned %d", method, resp.status)
                    return None
                data = await resp.json()
                if "error" in data:
                    logger.warning("Last.fm error: %s", data.get("message", ""))
                    return None
                return data
    except Exception as e:
        logger.warning("Last.fm request failed: %s", e)
        return None


def _normalize_track(t: dict, source: str = "lastfm") -> Optional[dict]:
    """Convert Last.fm track dict to our standard format."""
    name = t.get("name", "").strip()
    artist_info = t.get("artist")
    if isinstance(artist_info, dict):
        artist = artist_info.get("name", "").strip()
    elif isinstance(artist_info, str):
        artist = artist_info.strip()
    else:
        artist = ""

    if not name or not artist:
        return None

    # Last.fm doesn't provide audio — we'll search by title + artist later
    # Use a deterministic ID so we can deduplicate
    return {
        "title": name,
        "artist": artist,
        "duration": int(t.get("duration", 0)) // 1000 if t.get("duration") else 0,
        "source": source,
        "lastfm_match": float(t.get("match", 0)),
        # No video_id yet — caller must resolve to a playable source
    }


async def get_similar_tracks(
    title: str, artist: str, limit: int = 15
) -> list[dict]:
    """
    Get tracks similar to a given track using Last.fm's collaborative data.
    Returns normalized track dicts (without video_id — must be resolved).
    """
    cache_key = f"lfm_sim:{artist}:{title}:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = await _lastfm_get("track.getSimilar", {
        "track": title,
        "artist": artist,
        "limit": str(limit),
        "autocorrect": "1",
    })
    if not data:
        return []

    similar = data.get("similartracks", {}).get("track", [])
    if isinstance(similar, dict):
        similar = [similar]

    results = []
    seen_titles: set[str] = set()
    for t in similar:
        norm = _normalize_track(t)
        if norm:
            key = f"{norm['artist'].lower()}:{norm['title'].lower()}"
            if key not in seen_titles:
                seen_titles.add(key)
                results.append(norm)

    if results:
        _cache_set(cache_key, results)
    return results


async def get_similar_artists(artist: str, limit: int = 10) -> list[dict]:
    """
    Get similar artists from Last.fm.
    Returns list of {"name": str, "match": float}.
    """
    cache_key = f"lfm_art:{artist}:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = await _lastfm_get("artist.getSimilar", {
        "artist": artist,
        "limit": str(limit),
        "autocorrect": "1",
    })
    if not data:
        return []

    artists = data.get("similarartists", {}).get("artist", [])
    if isinstance(artists, dict):
        artists = [artists]

    results = [
        {"name": a.get("name", ""), "match": float(a.get("match", 0))}
        for a in artists
        if a.get("name")
    ]

    if results:
        _cache_set(cache_key, results)
    return results


async def get_artist_top_tracks(artist: str, limit: int = 5) -> list[dict]:
    """Get top tracks for an artist from Last.fm."""
    cache_key = f"lfm_top:{artist}:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = await _lastfm_get("artist.getTopTracks", {
        "artist": artist,
        "limit": str(limit),
        "autocorrect": "1",
    })
    if not data:
        return []

    tracks = data.get("toptracks", {}).get("track", [])
    if isinstance(tracks, dict):
        tracks = [tracks]

    results = []
    for t in tracks:
        norm = _normalize_track(t)
        if norm:
            results.append(norm)

    if results:
        _cache_set(cache_key, results)
    return results


async def discover_similar_flow(
    title: str, artist: str, limit: int = 10
) -> list[dict]:
    """
    Full flow discovery: similar tracks + similar artists' top tracks.
    Blends direct similarity with artist exploration.
    Returns tracks sorted by relevance (match score).
    """
    # Run both in parallel
    sim_tracks_task = get_similar_tracks(title, artist, limit=limit)
    sim_artists_task = get_similar_artists(artist, limit=5)

    sim_tracks, sim_artists = await asyncio.gather(
        sim_tracks_task, sim_artists_task
    )

    # Get top tracks from similar artists
    artist_tracks: list[dict] = []
    if sim_artists:
        tasks = [
            get_artist_top_tracks(a["name"], limit=3)
            for a in sim_artists[:5]
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, list):
                artist_tracks.extend(r)

    # Merge: similar tracks first, then artist tracks
    seen: set[str] = set()
    merged: list[dict] = []

    for t in sim_tracks:
        key = f"{t['artist'].lower()}:{t['title'].lower()}"
        if key not in seen:
            seen.add(key)
            t["_score"] = t.get("lastfm_match", 0.5)
            merged.append(t)

    for t in artist_tracks:
        key = f"{t['artist'].lower()}:{t['title'].lower()}"
        if key not in seen:
            seen.add(key)
            t["_score"] = 0.3  # Lower priority than direct similar
            merged.append(t)

    # Sort by score descending
    merged.sort(key=lambda x: x.get("_score", 0), reverse=True)
    return merged[:limit]


async def resolve_to_playable(
    tracks: list[dict], exclude_vids: set[str] | None = None
) -> list[dict]:
    """
    Resolve Last.fm tracks (title+artist only) to playable sources.
    Searches Deezer first (fast, good quality), then falls back to DB.
    """
    if not tracks:
        return []

    exclude = exclude_vids or set()
    resolved: list[dict] = []

    for t in tracks:
        query = f"{t['artist']} {t['title']}"

        # 1. Try our DB first (instant, already downloaded)
        try:
            from bot.models.base import async_session
            from bot.models.track import Track as TrackModel
            from sqlalchemy import select, or_, func

            async with async_session() as session:
                # Fuzzy match: artist + title
                row = (await session.execute(
                    select(TrackModel).where(
                        func.lower(TrackModel.artist).contains(t["artist"].lower()),
                        func.lower(TrackModel.title).contains(t["title"].lower()),
                    ).limit(1)
                )).scalar_one_or_none()
                if row and row.source_id and row.source_id not in exclude:
                    resolved.append({
                        "video_id": row.source_id,
                        "title": row.title or t["title"],
                        "artist": row.artist or t["artist"],
                        "duration": row.duration or t.get("duration", 0),
                        "duration_fmt": _fmt_dur(row.duration or 0),
                        "source": row.source or "db",
                        "cover_url": row.cover_url if hasattr(row, "cover_url") else None,
                    })
                    exclude.add(row.source_id)
                    continue
        except Exception:
            pass

        # 2. Deezer search (free, fast)
        try:
            from recommender.deezer_discovery import search_by_artist
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://api.deezer.com/search",
                    params={"q": query, "limit": "1"},
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        hits = data.get("data", [])
                        if hits:
                            h = hits[0]
                            vid = f"dz_{h['id']}"
                            if vid not in exclude:
                                resolved.append({
                                    "video_id": vid,
                                    "title": h.get("title", t["title"]),
                                    "artist": h.get("artist", {}).get("name", t["artist"]),
                                    "duration": h.get("duration", 0),
                                    "duration_fmt": _fmt_dur(h.get("duration", 0)),
                                    "source": "deezer",
                                    "cover_url": h.get("album", {}).get("cover_medium"),
                                })
                                exclude.add(vid)
                                continue
        except Exception:
            pass

    return resolved


def _fmt_dur(sec: int) -> str:
    if not sec:
        return "0:00"
    m, s = divmod(sec, 60)
    return f"{m}:{s:02d}"
