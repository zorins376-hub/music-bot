"""
supabase_mirror.py — fire-and-forget mirroring of key data to Supabase REST API.

Mirrors: users, tracks, playlists, playlist_tracks, favorite_tracks, listening_history.
All writes are async, non-blocking, and silently swallow errors so they never
affect the main bot flow.

Uses the Supabase PostgREST endpoint with service_role key (upsert via Prefer: merge-duplicates).
"""

import asyncio
import logging
from typing import Any

import aiohttp

from bot.config import settings

logger = logging.getLogger(__name__)

# ── Supabase REST credentials ────────────────────────────────────────────────

_SUPA_URL: str = (
    getattr(settings, "SUPABASE_URL", None)
    or "https://uhvbdwjchxcnoiodfnvw.supabase.co"
)
_SUPA_KEY: str = (
    getattr(settings, "SUPABASE_SERVICE_KEY", None)
    or "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVodmJkd2pjaHhjbm9pb2RmbnZ3Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MTg1MDAwOSwiZXhwIjoyMDg3NDI2MDA5fQ"
    ".tLm2O84rRZHgcoPQgbgb8zVC3zRCBzy54xS0qCF_6Gw"
)

_HEADERS = {
    "Authorization": f"Bearer {_SUPA_KEY}",
    "apikey": _SUPA_KEY,
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates",  # upsert
}

_session: aiohttp.ClientSession | None = None
_enabled: bool = bool(_SUPA_URL and _SUPA_KEY)


# ── Session management ────────────────────────────────────────────────────────

def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10),
        )
    return _session


async def close() -> None:
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None


# ── Low-level REST helpers ────────────────────────────────────────────────────

async def _upsert(table: str, payload: dict[str, Any]) -> None:
    """POST one row to Supabase REST (upsert). Fire-and-forget."""
    if not _enabled:
        return
    url = f"{_SUPA_URL}/rest/v1/{table}"
    try:
        s = _get_session()
        async with s.post(url, json=payload, headers=_HEADERS) as r:
            if r.status not in (200, 201):
                body = await r.text()
                logger.debug("mirror upsert %s %d: %s", table, r.status, body[:200])
    except Exception as e:
        logger.debug("mirror upsert %s error: %s", table, e)


async def _delete(table: str, filters: str) -> None:
    """DELETE rows from Supabase REST. Fire-and-forget."""
    if not _enabled:
        return
    url = f"{_SUPA_URL}/rest/v1/{table}?{filters}"
    try:
        s = _get_session()
        async with s.delete(url, headers=_HEADERS) as r:
            if r.status not in (200, 204):
                body = await r.text()
                logger.debug("mirror delete %s %d: %s", table, r.status, body[:200])
    except Exception as e:
        logger.debug("mirror delete %s error: %s", table, e)


def _fire(coro) -> None:
    """Schedule coroutine as fire-and-forget task."""
    try:
        asyncio.create_task(coro)
    except RuntimeError:
        pass  # no running loop (e.g. during tests)


# ── Public API ────────────────────────────────────────────────────────────────

def mirror_user(
    user_id: int,
    username: str | None = None,
    first_name: str | None = None,
    language: str | None = None,
    is_premium: bool = False,
    is_admin: bool = False,
    **extra,
) -> None:
    """Mirror user create/update to Supabase."""
    payload = {
        "id": user_id,
        "username": username,
        "first_name": first_name,
        "language": language or "ru",
        "is_premium": is_premium,
        "is_admin": is_admin,
    }
    payload.update({k: v for k, v in extra.items() if v is not None})
    _fire(_upsert("users", payload))


def mirror_track(
    track_id: int,
    source_id: str,
    source: str = "youtube",
    title: str | None = None,
    artist: str | None = None,
    **extra,
) -> None:
    """Mirror track upsert to Supabase."""
    payload = {
        "id": track_id,
        "source_id": source_id,
        "source": source,
        "title": title,
        "artist": artist,
    }
    payload.update({k: v for k, v in extra.items() if v is not None})
    _fire(_upsert("tracks", payload))


def mirror_playlist_create(playlist_id: int, user_id: int, name: str) -> None:
    """Mirror playlist creation."""
    _fire(_upsert("playlists", {
        "id": playlist_id,
        "user_id": user_id,
        "name": name,
    }))


def mirror_playlist_delete(playlist_id: int) -> None:
    """Mirror playlist deletion (cascade deletes playlist_tracks on Supabase)."""
    _fire(_delete("playlists", f"id=eq.{playlist_id}"))


def mirror_playlist_track_add(
    pt_id: int, playlist_id: int, track_id: int, position: int = 0,
) -> None:
    """Mirror adding a track to playlist."""
    _fire(_upsert("playlist_tracks", {
        "id": pt_id,
        "playlist_id": playlist_id,
        "track_id": track_id,
        "position": position,
    }))


def mirror_playlist_track_remove(pt_id: int) -> None:
    """Mirror removing a track from playlist by playlist_track ID."""
    _fire(_delete("playlist_tracks", f"id=eq.{pt_id}"))


def mirror_playlist_track_remove_by_ids(playlist_id: int, track_id: int) -> None:
    """Mirror removing a track from playlist by playlist_id + track_id."""
    _fire(_delete(
        "playlist_tracks",
        f"playlist_id=eq.{playlist_id}&track_id=eq.{track_id}",
    ))


def mirror_favorite_add(fav_id: int, user_id: int, track_id: int) -> None:
    """Mirror adding a favorite."""
    _fire(_upsert("favorite_tracks", {
        "id": fav_id,
        "user_id": user_id,
        "track_id": track_id,
    }))


def mirror_favorite_remove(user_id: int, track_id: int) -> None:
    """Mirror removing a favorite."""
    _fire(_delete(
        "favorite_tracks",
        f"user_id=eq.{user_id}&track_id=eq.{track_id}",
    ))


def mirror_listening_event(
    event_id: int,
    user_id: int,
    action: str = "play",
    track_id: int | None = None,
    query: str | None = None,
    source: str = "search",
    listen_duration: int | None = None,
) -> None:
    """Mirror listening_history row."""
    payload: dict[str, Any] = {
        "id": event_id,
        "user_id": user_id,
        "action": action,
        "source": source,
    }
    if track_id is not None:
        payload["track_id"] = track_id
    if query is not None:
        payload["query"] = query
    if listen_duration is not None:
        payload["listen_duration"] = listen_duration
    _fire(_upsert("listening_history", payload))
