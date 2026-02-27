"""Spotify provider — search and resolve via Spotify Web API (spotipy).

Requires SPOTIFY_CLIENT_ID + SPOTIFY_CLIENT_SECRET env vars.
If not configured — all functions return [] / None gracefully.

NOTE: Spotify does not allow direct audio downloads.
Tracks found via Spotify are downloaded through Yandex Music or YouTube.
"""
import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor

from bot.config import settings

logger = logging.getLogger(__name__)

_sp_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="spotify")

_sp_client = None

_SPOTIFY_TRACK_RE = re.compile(
    r"https?://open\.spotify\.com/(?:intl-[a-z]{2}/)?track/([a-zA-Z0-9]{22})"
)
_SPOTIFY_URL_RE = re.compile(
    r"https?://open\.spotify\.com/(?:intl-[a-z]{2}/)?track/[a-zA-Z0-9]{22}"
)


def _get_client():
    global _sp_client
    if _sp_client is not None:
        return _sp_client
    cid = settings.SPOTIFY_CLIENT_ID
    secret = settings.SPOTIFY_CLIENT_SECRET
    if not cid or not secret:
        return None
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyClientCredentials
        auth = SpotifyClientCredentials(client_id=cid, client_secret=secret)
        _sp_client = spotipy.Spotify(auth_manager=auth, requests_timeout=10)
        logger.info("Spotify provider initialised")
        return _sp_client
    except Exception as e:
        logger.error("Spotify init failed: %s", e)
        return None


def _fmt_dur(ms: int) -> str:
    s = ms // 1000
    m, sec = divmod(s, 60)
    return f"{m}:{sec:02d}"


def _track_to_dict(track: dict) -> dict | None:
    """Convert Spotify API track object to internal dict."""
    try:
        title = (track.get("name") or "").strip()
        artists = track.get("artists") or []
        artist = ", ".join(a["name"] for a in artists if a.get("name")).strip()
        if not title or not artist:
            return None
        dur_ms = track.get("duration_ms") or 0
        dur_s = dur_ms // 1000
        if dur_s > settings.MAX_DURATION:
            return None
        track_id = track.get("id") or ""
        if not track_id:
            return None
        return {
            "video_id": f"sp_{track_id}",
            "spotify_id": track_id,
            "title": title,
            "uploader": artist,
            "duration": dur_s,
            "duration_fmt": _fmt_dur(dur_ms),
            "source": "spotify",
            "yt_query": f"{artist} - {title}",
        }
    except Exception:
        return None


def _search_sync(query: str, limit: int) -> list[dict]:
    sp = _get_client()
    if sp is None:
        return []
    try:
        result = sp.search(q=query, type="track", limit=min(limit + 5, 50))
        items = (result or {}).get("tracks", {}).get("items", [])
        tracks = []
        for item in items:
            d = _track_to_dict(item)
            if d:
                tracks.append(d)
            if len(tracks) >= limit:
                break
        return tracks
    except Exception as e:
        logger.error("Spotify search error: %s", e)
        return []


def _resolve_sync(url: str) -> dict | None:
    m = _SPOTIFY_TRACK_RE.search(url)
    if not m:
        return None
    track_id = m.group(1)
    sp = _get_client()
    if sp is None:
        return None
    try:
        track = sp.track(track_id)
        if not track:
            return None
        return _track_to_dict(track)
    except Exception as e:
        logger.error("Spotify resolve error for %s: %s", track_id, e)
        return None


# ── Public async API ──────────────────────────────────────────────────────

def is_spotify_url(text: str) -> bool:
    return bool(_SPOTIFY_URL_RE.search(text))


async def search_spotify(query: str, limit: int = 5) -> list[dict]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_sp_pool, _search_sync, query, limit)


async def resolve_spotify_url(url: str) -> dict | None:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_sp_pool, _resolve_sync, url)
