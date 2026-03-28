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


# ── New Last.fm discovery functions ──────────────────────────────────────

async def get_top_by_tag(tag: str, limit: int = 20) -> list[dict]:
    """Get top tracks for a genre/mood tag (e.g. 'indie', 'lo-fi', 'hip-hop')."""
    cache_key = f"lfm_tag:{tag}:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = await _lastfm_get("tag.getTopTracks", {
        "tag": tag,
        "limit": str(limit),
    })
    if not data:
        return []

    tracks = data.get("tracks", {}).get("track", [])
    if isinstance(tracks, dict):
        tracks = [tracks]

    results = []
    seen: set[str] = set()
    for t in tracks:
        norm = _normalize_track(t, source="lastfm_tag")
        if norm:
            key = f"{norm['artist'].lower()}:{norm['title'].lower()}"
            if key not in seen:
                seen.add(key)
                results.append(norm)

    if results:
        _cache_set(cache_key, results)
    return results


_COUNTRY_TAGS: dict[str, list[str]] = {
    "Russian Federation": ["russian", "russian pop", "russian rock", "russian hip-hop"],
    "Kazakhstan": ["kazakh", "russian pop", "post-soviet"],
    "Kyrgyzstan": ["russian pop", "central asian", "post-soviet"],
    "United States": ["american", "us pop", "hip-hop", "r&b"],
    "United Kingdom": ["british", "uk", "britpop", "uk drill"],
    "Germany": ["german", "deutsche", "german pop", "german rap"],
    "Turkey": ["turkish", "turkish pop", "turkish rock"],
    "France": ["french", "french pop", "french rap", "chanson"],
    "Brazil": ["brazilian", "mpb", "sertanejo", "funk brasileiro"],
    "Japan": ["japanese", "j-pop", "j-rock", "anime"],
    "Korea, Republic of": ["korean", "k-pop", "k-indie", "k-rap"],
    "India": ["indian", "bollywood", "hindi", "punjabi"],
}

_MAX_PER_ARTIST = 2  # max tracks from one artist in geo results


async def get_geo_top_tracks(country: str = "russia", limit: int = 20) -> list[dict]:
    """Get trending tracks in a specific country via Last.fm geo data + regional tags for diversity."""
    cache_key = f"lfm_geo_v2:{country}:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    import asyncio as _aio
    import random

    # Fetch geo top + regional tag tracks in parallel for diversity
    country_tags = _COUNTRY_TAGS.get(country, [])
    tag = random.choice(country_tags) if country_tags else None

    coros = [
        _lastfm_get("geo.getTopTracks", {"country": country, "limit": str(limit + 20)}),
    ]
    if tag:
        coros.append(_lastfm_get("tag.getTopTracks", {"tag": tag, "limit": str(limit)}))

    fetched = await _aio.gather(*coros, return_exceptions=True)

    geo_data = fetched[0] if not isinstance(fetched[0], Exception) else None
    tag_data = fetched[1] if len(fetched) > 1 and not isinstance(fetched[1], Exception) else None

    results = []
    seen: set[str] = set()
    artist_count: dict[str, int] = {}

    def _add_tracks(data, source: str):
        if not data:
            return
        key_path = "tracks" if "tracks" in data else "toptracks"
        tracks = data.get(key_path, data).get("track", [])
        if isinstance(tracks, dict):
            tracks = [tracks]
        for t in tracks:
            norm = _normalize_track(t, source=source)
            if norm:
                key = f"{norm['artist'].lower()}:{norm['title'].lower()}"
                artist_key = norm['artist'].lower()
                if key not in seen and artist_count.get(artist_key, 0) < _MAX_PER_ARTIST:
                    seen.add(key)
                    artist_count[artist_key] = artist_count.get(artist_key, 0) + 1
                    norm["listeners"] = int(t.get("listeners", 0))
                    results.append(norm)

    # Geo tracks first (higher priority)
    _add_tracks(geo_data, "lastfm_geo")
    # Then regional tag tracks to fill gaps
    _add_tracks(tag_data, "lastfm_tag")

    # Shuffle a bit to mix geo and tag results but keep top ones first
    if len(results) > 6:
        top = results[:4]
        rest = results[4:]
        random.shuffle(rest)
        results = top + rest

    results = results[:limit]

    if results:
        _cache_set(cache_key, results)
    return results


async def get_global_chart(limit: int = 20) -> list[dict]:
    """Get Last.fm global chart — based on 20+ years of listening data."""
    cache_key = f"lfm_chart:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = await _lastfm_get("chart.getTopTracks", {
        "limit": str(limit),
    })
    if not data:
        return []

    tracks = data.get("tracks", {}).get("track", [])
    if isinstance(tracks, dict):
        tracks = [tracks]

    results = []
    seen: set[str] = set()
    for t in tracks:
        norm = _normalize_track(t, source="lastfm_chart")
        if norm:
            key = f"{norm['artist'].lower()}:{norm['title'].lower()}"
            if key not in seen:
                seen.add(key)
                norm["playcount"] = int(t.get("playcount", 0))
                norm["listeners"] = int(t.get("listeners", 0))
                results.append(norm)

    if results:
        _cache_set(cache_key, results)
    return results


async def get_top_tags(limit: int = 30) -> list[dict]:
    """Get top tags/genres from Last.fm for tag cloud / genre picker."""
    cache_key = f"lfm_toptags:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = await _lastfm_get("chart.getTopTags", {
        "limit": str(limit),
    })
    if not data:
        return []

    tags = data.get("tags", {}).get("tag", [])
    if isinstance(tags, dict):
        tags = [tags]

    results = [
        {"name": t.get("name", ""), "reach": int(t.get("reach", 0)),
         "count": int(t.get("taggings", 0))}
        for t in tags if t.get("name")
    ]

    if results:
        _cache_set(cache_key, results)
    return results


async def get_artist_info(artist: str) -> Optional[dict]:
    """Get artist bio, tags, stats from Last.fm."""
    cache_key = f"lfm_artinfo:{artist}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = await _lastfm_get("artist.getInfo", {
        "artist": artist,
        "autocorrect": "1",
    })
    if not data:
        return None

    info = data.get("artist", {})
    tags = info.get("tags", {}).get("tag", [])
    if isinstance(tags, dict):
        tags = [tags]

    # Extract artist image (prefer large/extralarge)
    images = info.get("image", [])
    image_url = ""
    if isinstance(images, list):
        for img in reversed(images):  # Last = largest
            url = img.get("#text", "") if isinstance(img, dict) else ""
            if url and not url.endswith("2a96cbd8b46e442fc41c2b86b821562f.png"):
                image_url = url
                break

    result = {
        "name": info.get("name", artist),
        "listeners": int(info.get("stats", {}).get("listeners", 0)),
        "playcount": int(info.get("stats", {}).get("playcount", 0)),
        "tags": [t.get("name", "") for t in tags if t.get("name")],
        "bio": (info.get("bio", {}).get("summary", "") or "").split("<a ")[0].strip(),
        "image": image_url,
        "similar": [
            a.get("name", "")
            for a in (info.get("similar", {}).get("artist", []) or [])
            if a.get("name")
        ][:5],
    }

    _cache_set(cache_key, result)
    return result


async def get_new_from_favorites(
    favorite_artists: list[str], limit: int = 15
) -> list[dict]:
    """
    Get fresh/top tracks from user's favorite artists.
    Uses artist.getTopTracks for each favorite artist and interleaves results.
    """
    if not favorite_artists:
        return []

    tasks = [
        get_artist_top_tracks(art, limit=5)
        for art in favorite_artists[:8]  # max 8 artists
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    merged: list[dict] = []
    seen: set[str] = set()
    for r in results:
        if isinstance(r, list):
            for t in r:
                key = f"{t['artist'].lower()}:{t['title'].lower()}"
                if key not in seen:
                    seen.add(key)
                    t["source"] = "lastfm_favorites"
                    merged.append(t)

    # Interleave: don't cluster by artist
    import random
    random.shuffle(merged)
    return merged[:limit]


async def get_similar_artists_mix(artist: str, limit: int = 15) -> list[dict]:
    """
    Deep artist discovery: get similar artists and their top tracks.
    Great for "If you like X, try..." sections.
    """
    sim_artists = await get_similar_artists(artist, limit=8)
    if not sim_artists:
        return []

    tasks = [
        get_artist_top_tracks(a["name"], limit=3)
        for a in sim_artists[:8]
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    merged: list[dict] = []
    seen: set[str] = set()
    for r in results:
        if isinstance(r, list):
            for t in r:
                key = f"{t['artist'].lower()}:{t['title'].lower()}"
                if key not in seen:
                    seen.add(key)
                    t["source"] = "lastfm_discover"
                    merged.append(t)

    import random
    random.shuffle(merged)
    return merged[:limit]
