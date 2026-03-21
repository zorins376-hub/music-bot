"""
playlist_import.py — Import playlists from Spotify, Yandex Music, and Apple Music.

Fetches track list from external services, searches each track
via search_tracks, and creates a Playlist with found tracks.
"""
import asyncio
import logging
import re
from typing import Callable, Optional

from bot.config import settings
from bot.services.downloader import search_tracks

logger = logging.getLogger(__name__)

# Type alias for progress callback: (found_count, total_count) -> None
ProgressCallback = Optional[Callable[[int, int], object]]

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

_APPLE_MUSIC_PLAYLIST_RE = re.compile(
    r"https?://music\.apple\.com/[a-z]{2}/playlist/[^/]+/(pl\.[a-zA-Z0-9]+)"
)


# ── VK Music playlist import ────────────────────────────────────────────

_VK_PLAYLIST_RE = re.compile(
    r"https?://(?:m\.)?vk\.com/music/playlist/(-?\d+)_(\d+)(?:_([a-zA-Z0-9]+))?"
)


async def fetch_vk_playlist(url: str) -> tuple[str, list[dict]]:
    """Fetch VK Music playlist name and tracks via vk_api."""
    m = _VK_PLAYLIST_RE.search(url)
    if not m:
        return ("", [])

    owner_id = int(m.group(1))
    playlist_id = int(m.group(2))
    access_key = m.group(3) or ""

    if not settings.VK_TOKEN:
        logger.warning("No VK_TOKEN for playlist import")
        return ("", [])

    try:
        from bot.services.vk_provider import _get_vk_audio
        import asyncio

        def _fetch_sync():
            try:
                import vk_api
                session = vk_api.VkApi(token=settings.VK_TOKEN)
                vk = session.get_api()

                # Get playlist info
                try:
                    pl_info = vk.audio.getPlaylistById(
                        owner_id=owner_id,
                        playlist_id=playlist_id,
                        access_key=access_key,
                    )
                    name = pl_info.get("title", "VK Import")
                except Exception:
                    name = "VK Import"

                # Get playlist tracks
                try:
                    resp = vk.audio.get(
                        owner_id=owner_id,
                        playlist_id=playlist_id,
                        access_key=access_key,
                        count=200,
                    )
                    items = resp.get("items", [])
                except Exception:
                    # Fallback: try via vk_audio
                    vk_audio = _get_vk_audio()
                    if vk_audio is None:
                        return (name, [])
                    items = list(vk_audio.get_iter(owner_id=owner_id, album_id=playlist_id, access_hash=access_key))

                result = []
                for item in items[:200]:
                    artist = item.get("artist", "")
                    title = item.get("title", "")
                    duration = item.get("duration", 0)
                    if not title:
                        continue
                    result.append({
                        "title": title,
                        "uploader": artist,
                        "duration": int(duration) if duration else 0,
                        "yt_query": f"{artist} - {title}",
                    })
                return (name, result)
            except Exception as e:
                logger.error("VK playlist fetch error: %s", e)
                return ("", [])

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fetch_sync)

    except Exception as e:
        logger.error("VK playlist import error: %s", e)
        return ("", [])


async def fetch_apple_music_playlist(url: str) -> tuple[str, list[dict]]:
    """Fetch Apple Music playlist by scraping the public page."""
    m = _APPLE_MUSIC_PLAYLIST_RE.search(url)
    if not m:
        return ("", [])

    try:
        from bot.services.http_session import get_session
        session = await get_session()

        async with session.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=15,
        ) as resp:
            if resp.status != 200:
                logger.warning("Apple Music page error: %d", resp.status)
                return ("", [])
            html = await resp.text()

        try:
            from bs4 import BeautifulSoup
        except ImportError:
            logger.warning("beautifulsoup4 not installed, Apple Music import unavailable")
            return ("", [])

        soup = BeautifulSoup(html, "html.parser")

        # Get playlist name from <title>
        title_tag = soup.find("title")
        name = title_tag.text.split(" - ")[0].strip() if title_tag else "Apple Music Import"

        result = []
        # Apple Music renders track info in meta tags and JSON-LD
        import json as _json
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = _json.loads(script.string or "")
                if data.get("@type") == "MusicPlaylist":
                    for item in data.get("track", []):
                        artist = item.get("byArtist", {}).get("name", "")
                        title = item.get("name", "")
                        if artist and title:
                            result.append({
                                "title": title,
                                "uploader": artist,
                                "duration": 0,
                                "yt_query": f"{artist} - {title}",
                            })
            except Exception:
                continue

        # Fallback: parse meta tags if JSON-LD didn't work
        if not result:
            for meta in soup.find_all("meta", property="music:song"):
                content = meta.get("content", "")
                if content:
                    # Try to extract artist - title from the URL or nearby elements
                    parts = content.rsplit("/", 1)
                    if parts:
                        slug = parts[-1].replace("-", " ")
                        result.append({
                            "title": slug,
                            "uploader": "",
                            "duration": 0,
                            "yt_query": slug,
                        })

        return (name, result[:200])

    except Exception as e:
        logger.error("Apple Music playlist fetch error: %s", e)
        return ("", [])


def detect_playlist_url(text: str) -> Optional[str]:
    """Detect if text contains a Spotify, Yandex, Apple Music, or VK Music playlist URL.

    Returns 'spotify', 'yandex', 'apple', 'vk', or None.
    """
    if _SPOTIFY_PLAYLIST_RE.search(text):
        return "spotify"
    if _YANDEX_PLAYLIST_RE.search(text):
        return "yandex"
    if _APPLE_MUSIC_PLAYLIST_RE.search(text):
        return "apple"
    if _VK_PLAYLIST_RE.search(text):
        return "vk"
    return None


async def import_playlist_tracks(
    url: str,
    source: str,
    progress_cb: ProgressCallback = None,
) -> tuple[str, list[dict], int]:
    """Import tracks from external playlist.

    Returns (playlist_name, found_tracks, total_count).
    found_tracks are search_tracks-compatible dicts.
    progress_cb is called with (found_so_far, total) periodically.
    """
    if source == "spotify":
        name, ext_tracks = await fetch_spotify_playlist(url)
    elif source == "yandex":
        name, ext_tracks = await fetch_yandex_playlist(url)
    elif source == "apple":
        name, ext_tracks = await fetch_apple_music_playlist(url)
    elif source == "vk":
        name, ext_tracks = await fetch_vk_playlist(url)
    else:
        return ("", [], 0)

    if not ext_tracks:
        return (name or "Imported", [], 0)

    total = len(ext_tracks)

    # Search tracks in parallel batches of 5
    found: list[dict] = []
    seen_ids: set[str] = set()
    batch_size = 5

    for i in range(0, len(ext_tracks), batch_size):
        batch = ext_tracks[i:i + batch_size]
        tasks = []
        for tr in batch:
            query = tr.get("yt_query") or f"{tr.get('uploader', '')} - {tr.get('title', '')}"
            tasks.append(search_tracks(query.strip(), max_results=1, source="youtube"))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, list) and res:
                vid = res[0].get("video_id", "")
                if vid and vid not in seen_ids:
                    seen_ids.add(vid)
                    found.append(res[0])

        # Progress callback
        if progress_cb:
            try:
                result = progress_cb(len(found), total)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.debug("import progress callback failed", exc_info=True)

        await asyncio.sleep(0.2)

    return (name, found, total)
