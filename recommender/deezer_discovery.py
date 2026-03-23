"""
Deezer-powered music discovery — find new tracks based on user taste.

Uses free Deezer API (no auth required):
  - /search?q=artist:"X" → tracks by artist
  - /artist/{id}/related → similar artists
  - /artist/{id}/top → top tracks of artist
  - /chart/{genre_id}/tracks → genre charts

This provides infinite discovery beyond the local DB.
"""
import asyncio
import hashlib
import json
import logging
import random
import time
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

_DEEZER_API = "https://api.deezer.com"

# Simple in-memory cache with TTL
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
    # Evict oldest if too many
    if len(_cache) >= _CACHE_MAX:
        oldest = min(_cache, key=lambda k: _cache[k][0])
        del _cache[oldest]
    _cache[key] = (time.time(), val)


async def _deezer_get(path: str, params: dict | None = None) -> dict | list | None:
    """Make a GET request to Deezer API."""
    url = f"{_DEEZER_API}{path}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
                if isinstance(data, dict) and data.get("error"):
                    return None
                return data
    except Exception as e:
        logger.debug("Deezer API error: %s", e)
        return None


def _deezer_track_to_dict(t: dict) -> dict:
    """Convert Deezer track object to our standard format."""
    artist = t.get("artist", {})
    album = t.get("album", {})
    duration = t.get("duration", 0)

    # Build video_id from deezer ID
    dz_id = t.get("id", 0)

    # Get best cover
    cover_url = (
        album.get("cover_xl")
        or album.get("cover_big")
        or album.get("cover_medium")
        or album.get("cover")
        or None
    )

    return {
        "video_id": f"dz_{dz_id}",
        "title": t.get("title_short") or t.get("title") or "Unknown",
        "artist": artist.get("name") or "Unknown",
        "duration": duration,
        "duration_fmt": f"{duration // 60}:{duration % 60:02d}" if duration else "0:00",
        "source": "deezer",
        "cover_url": cover_url,
        "deezer_id": dz_id,
    }


async def search_by_artist(artist_name: str, limit: int = 10) -> list[dict]:
    """Search Deezer for tracks by artist name."""
    cache_key = f"dz_artist:{artist_name}:{limit}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    data = await _deezer_get("/search", {"q": f'artist:"{artist_name}"', "limit": limit})
    if not data or not isinstance(data, dict):
        return []

    tracks = [_deezer_track_to_dict(t) for t in data.get("data", []) if t.get("id")]
    _cache_set(cache_key, tracks)
    return tracks


async def get_related_artists(artist_name: str, limit: int = 5) -> list[dict]:
    """Find related artists via Deezer."""
    cache_key = f"dz_related:{artist_name}"
    cached = _cache_get(cache_key)
    if cached:
        return cached[:limit]

    # First find the artist ID
    search = await _deezer_get("/search/artist", {"q": artist_name, "limit": 1})
    if not search or not isinstance(search, dict):
        return []

    artists = search.get("data", [])
    if not artists:
        return []

    artist_id = artists[0].get("id")
    if not artist_id:
        return []

    # Get related artists
    data = await _deezer_get(f"/artist/{artist_id}/related", {"limit": limit})
    if not data or not isinstance(data, dict):
        return []

    result = [
        {"id": a.get("id"), "name": a.get("name"), "picture": a.get("picture_medium")}
        for a in data.get("data", [])
        if a.get("id") and a.get("name")
    ]
    _cache_set(cache_key, result)
    return result[:limit]


async def get_artist_top_tracks(artist_name: str, limit: int = 10) -> list[dict]:
    """Get top tracks of an artist via Deezer."""
    cache_key = f"dz_top:{artist_name}:{limit}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    # Find artist ID
    search = await _deezer_get("/search/artist", {"q": artist_name, "limit": 1})
    if not search or not isinstance(search, dict):
        return []

    artists = search.get("data", [])
    if not artists:
        return []

    artist_id = artists[0].get("id")
    if not artist_id:
        return []

    data = await _deezer_get(f"/artist/{artist_id}/top", {"limit": limit})
    if not data or not isinstance(data, dict):
        return []

    tracks = [_deezer_track_to_dict(t) for t in data.get("data", []) if t.get("id")]
    _cache_set(cache_key, tracks)
    return tracks


async def get_genre_tracks(genre_id: int = 0, limit: int = 20) -> list[dict]:
    """Get chart tracks for a genre. genre_id=0 means all genres."""
    cache_key = f"dz_genre:{genre_id}:{limit}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    data = await _deezer_get(f"/chart/{genre_id}/tracks", {"limit": limit})
    if not data or not isinstance(data, dict):
        return []

    tracks = [_deezer_track_to_dict(t) for t in data.get("data", []) if t.get("id")]
    _cache_set(cache_key, tracks)
    return tracks


# Mood → Deezer genre mapping
MOOD_GENRES = {
    "chill": [455, 466],      # Ambient, Lounge
    "energy": [152, 113],     # Rock, Dance
    "focus": [455, 98],       # Ambient, Classical
    "romance": [132, 197],    # Pop, R&B
    "party": [113, 464],      # Dance, Electro
    "melancholy": [165, 85],  # Indie, Alternative
}

# Mood → search queries for more variety
MOOD_QUERIES = {
    "chill": ["chill vibes", "lo-fi", "ambient relax", "soft acoustic"],
    "energy": ["workout music", "high energy", "power rock", "pump up"],
    "focus": ["study music", "deep focus", "concentration", "instrumental"],
    "romance": ["love songs", "romantic", "slow dance", "ballad"],
    "party": ["party hits", "club music", "dance floor", "EDM"],
    "melancholy": ["sad songs", "melancholy", "emotional", "rainy day"],
}


async def discover_by_mood(mood: str, limit: int = 15) -> list[dict]:
    """Discover tracks by mood using Deezer genres + search."""
    cache_key = f"dz_mood:{mood}:{limit}"
    cached = _cache_get(cache_key)
    if cached:
        return random.sample(cached, min(limit, len(cached)))

    all_tracks: list[dict] = []
    seen_ids: set[str] = set()

    # Get from genre charts
    genre_ids = MOOD_GENRES.get(mood, [0])
    for gid in genre_ids[:2]:
        tracks = await get_genre_tracks(gid, limit=20)
        for t in tracks:
            if t["video_id"] not in seen_ids:
                seen_ids.add(t["video_id"])
                all_tracks.append(t)

    # Search by mood queries
    queries = MOOD_QUERIES.get(mood, [mood])
    for q in random.sample(queries, min(2, len(queries))):
        data = await _deezer_get("/search", {"q": q, "limit": 15})
        if data and isinstance(data, dict):
            for t in data.get("data", []):
                track = _deezer_track_to_dict(t)
                if track["video_id"] not in seen_ids:
                    seen_ids.add(track["video_id"])
                    all_tracks.append(track)

    random.shuffle(all_tracks)
    _cache_set(cache_key, all_tracks)
    return all_tracks[:limit]


async def discover_for_user(
    top_artists: list[str],
    listened_video_ids: set[str] | None = None,
    limit: int = 15,
) -> list[dict]:
    """
    Discover new tracks for a user based on their top artists.

    Algorithm:
    1. For each top artist → get their tracks from Deezer (not in DB)
    2. For top 3 artists → find related artists → get their top tracks
    3. Mix and deduplicate
    4. Filter out already-listened tracks

    Returns diverse list of discovery tracks.
    """
    if not top_artists:
        # Fallback: global chart
        return await get_genre_tracks(0, limit)

    listened = listened_video_ids or set()
    all_tracks: list[dict] = []
    seen_ids: set[str] = set()

    async def add_tracks(tracks: list[dict]):
        for t in tracks:
            vid = t["video_id"]
            if vid not in seen_ids and vid not in listened:
                seen_ids.add(vid)
                all_tracks.append(t)

    # 1. Top tracks from user's favorite artists
    artist_tasks = [get_artist_top_tracks(a, limit=8) for a in top_artists[:5]]
    artist_results = await asyncio.gather(*artist_tasks, return_exceptions=True)
    for res in artist_results:
        if isinstance(res, list):
            await add_tracks(res)

    # 2. Related artists discovery (from top 3)
    related_tasks = [get_related_artists(a, limit=3) for a in top_artists[:3]]
    related_results = await asyncio.gather(*related_tasks, return_exceptions=True)

    related_artist_names: list[str] = []
    for res in related_results:
        if isinstance(res, list):
            for a in res:
                name = a.get("name", "")
                if name and name.lower() not in {x.lower() for x in top_artists}:
                    related_artist_names.append(name)

    # Get top tracks from related artists
    if related_artist_names:
        unique_related = list(dict.fromkeys(related_artist_names))[:5]
        rel_tasks = [get_artist_top_tracks(name, limit=5) for name in unique_related]
        rel_results = await asyncio.gather(*rel_tasks, return_exceptions=True)
        for res in rel_results:
            if isinstance(res, list):
                await add_tracks(res)

    # 3. Shuffle and return
    random.shuffle(all_tracks)
    return all_tracks[:limit]


async def find_similar_via_deezer(title: str, artist: str, limit: int = 10) -> list[dict]:
    """Find similar tracks to a given track via Deezer search."""
    cache_key = f"dz_sim:{artist}:{title}:{limit}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    all_tracks: list[dict] = []
    seen: set[str] = set()

    # 1. More tracks by same artist
    artist_tracks = await search_by_artist(artist, limit=10)
    for t in artist_tracks:
        # Skip the exact same track
        if t["title"].lower() != title.lower() and t["video_id"] not in seen:
            seen.add(t["video_id"])
            all_tracks.append(t)

    # 2. Related artists' top tracks
    related = await get_related_artists(artist, limit=3)
    for rel in related:
        name = rel.get("name")
        if name:
            tracks = await get_artist_top_tracks(name, limit=3)
            for t in tracks:
                if t["video_id"] not in seen:
                    seen.add(t["video_id"])
                    all_tracks.append(t)

    result = all_tracks[:limit]
    if result:
        _cache_set(cache_key, result)
    return result
