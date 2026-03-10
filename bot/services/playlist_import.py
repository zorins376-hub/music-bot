"""
playlist_import.py — Import playlists from Spotify and Yandex Music.

Fetches track list from external services, searches each track
via search_tracks, and creates a Playlist with found tracks.
"""
import asyncio
import logging
import re
from typing import Optional

from bot.config import settings
from bot.services.downloader import search_tracks

logger = logging.getLogger(__name__)

# ── Spotify playlist import ─────────────────────────────────────────────

_SPOTIFY_PLAYLIST_RE = re.compile(
    r"https?://open\.spotify\.com/(?:intl-[a-z]{2}/)?playlist/([a-zA-Z0-9]+)"
)


def _fetch_spotify_playlist_sync(playlist_id: str) -> tuple[str, list[dict]]:
    """Fetch Spotify playlist tracks (sync, runs in thread pool).

    Returns (playlist_name, list_of_track_dicts).
    """
    from bot.services.spotify_provider import _get_client, _track_to_dict
    sp = _get_client()
    if sp is None:
        return ("", [])

    try:
        pl = sp.playlist(playlist_id, fields="name,tracks.total,tracks.items(track(id,name,artists,duration_ms)),tracks.next")
        name = pl.get("name", "Imported")
        tracks_data = pl.get("tracks", {})
        items = tracks_data.get("items", [])

        result = []
        for item in items:
            track = item.get("track")
            if not track:
                continue
            d = _track_to_dict(track)
            if d:
                result.append(d)

        # Handle pagination (Spotify returns max 100 per page)
        next_url = tracks_data.get("next")
        while next_url and len(result) < 200:
            page = sp.next(tracks_data)
            if not page:
                break
            tracks_data = page
            for item in tracks_data.get("items", []):
                track = item.get("track")
                if not track:
                    continue
                d = _track_to_dict(track)
                if d:
                    result.append(d)
            next_url = tracks_data.get("next")

        return (name, result)

    except Exception as e:
        logger.error("Spotify playlist fetch error: %s", e)
        return ("", [])


async def fetch_spotify_playlist(url: str) -> tuple[str, list[dict]]:
    """Fetch Spotify playlist name and tracks."""
    m = _SPOTIFY_PLAYLIST_RE.search(url)
    if not m:
        return ("", [])
    playlist_id = m.group(1)

    from bot.services.spotify_provider import _sp_pool
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _sp_pool, _fetch_spotify_playlist_sync, playlist_id
    )


# ── Yandex Music playlist import ────────────────────────────────────────

_YANDEX_PLAYLIST_RE = re.compile(
    r"https?://music\.yandex\.(?:ru|com|by|kz|uz)/users/([^/]+)/playlists/(\d+)"
)


async def fetch_yandex_playlist(url: str) -> tuple[str, list[dict]]:
    """Fetch Yandex Music playlist name and tracks."""
    m = _YANDEX_PLAYLIST_RE.search(url)
    if not m:
        return ("", [])

    owner = m.group(1)
    kind = m.group(2)

    token = settings.YANDEX_MUSIC_TOKEN
    if not token:
        logger.warning("No YANDEX_MUSIC_TOKEN for playlist import")
        return ("", [])

    try:
        from bot.services.http_session import get_session
        session = get_session()

        async with session.get(
            f"https://api.music.yandex.net/users/{owner}/playlists/{kind}",
            headers={"Authorization": f"OAuth {token}"},
            timeout=15,
        ) as resp:
            if resp.status != 200:
                logger.warning("Yandex playlist API error: %d", resp.status)
                return ("", [])
            data = await resp.json()

        playlist = data.get("result", {})
        name = playlist.get("title", "Imported")
        tracks_list = playlist.get("tracks", [])

        result = []
        for item in tracks_list:
            track = item.get("track", {})
            title = track.get("title", "")
            artists = track.get("artists", [])
            artist = ", ".join(a.get("name", "") for a in artists if a.get("name"))
            dur_ms = track.get("durationMs", 0)
            dur_s = dur_ms // 1000 if dur_ms else 0

            if not title or not artist:
                continue

            result.append({
                "title": title,
                "uploader": artist,
                "duration": dur_s,
                "yt_query": f"{artist} - {title}",
            })

        return (name, result)

    except Exception as e:
        logger.error("Yandex playlist fetch error: %s", e)
        return ("", [])


# ── URL detection helpers ────────────────────────────────────────────────

def detect_playlist_url(text: str) -> Optional[str]:
    """Detect if text contains a Spotify or Yandex playlist URL.

    Returns 'spotify', 'yandex', or None.
    """
    if _SPOTIFY_PLAYLIST_RE.search(text):
        return "spotify"
    if _YANDEX_PLAYLIST_RE.search(text):
        return "yandex"
    return None


async def import_playlist_tracks(
    url: str,
    source: str,
) -> tuple[str, list[dict], int]:
    """Import tracks from external playlist.

    Returns (playlist_name, found_tracks, total_count).
    found_tracks are search_tracks-compatible dicts.
    """
    if source == "spotify":
        name, ext_tracks = await fetch_spotify_playlist(url)
    elif source == "yandex":
        name, ext_tracks = await fetch_yandex_playlist(url)
    else:
        return ("", [], 0)

    if not ext_tracks:
        return (name or "Imported", [], 0)

    total = len(ext_tracks)

    # Search each track to find downloadable version
    found: list[dict] = []
    seen_ids: set[str] = set()

    for tr in ext_tracks:
        query = tr.get("yt_query") or f"{tr.get('uploader', '')} - {tr.get('title', '')}"
        try:
            results = await search_tracks(query.strip(), max_results=1, source="youtube")
            if results:
                vid = results[0].get("video_id", "")
                if vid and vid not in seen_ids:
                    seen_ids.add(vid)
                    found.append(results[0])
        except Exception:
            pass
        # Small delay to avoid rate limiting
        await asyncio.sleep(0.3)

    return (name, found, total)
