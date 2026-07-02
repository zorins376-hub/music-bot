"""VK Music Provider — search and download via vk_api.

Requires a Kate Mobile / VK Android token set via VK_TOKEN env var.
Falls back gracefully (returns []) if the library is not installed or
the token is missing / invalid.
"""
import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import aiohttp

from bot.config import settings
from bot.services.downloader import cleanup_staged_files, finalize_staged_file, stage_path_for
from bot.services.http_session import get_session
from bot.utils import fmt_duration as _fmt_dur

logger = logging.getLogger(__name__)

# VPS-optimized: larger pool for VK API calls
_vk_pool = ThreadPoolExecutor(
    max_workers=max(2, settings.YTDL_WORKERS // 2),
    thread_name_prefix="vk"
)
_vk_session: object = None  # cached vk_api.VkApi session for direct API calls
_vk_audio: object = None   # cached VkAudio instance


def _get_vk_session():
    global _vk_session
    if _vk_session is not None:
        return _vk_session
    if not settings.VK_TOKEN:
        return None
    try:
        import vk_api
        _vk_session = vk_api.VkApi(token=settings.VK_TOKEN)
        return _vk_session
    except ImportError:
        logger.warning("vk_api not installed — VK provider disabled")
    except Exception as e:
        logger.error("VK init failed: %s", e)
    return None


def _get_vk_audio():
    global _vk_audio
    if _vk_audio is not None:
        return _vk_audio
    session = _get_vk_session()
    if session is None:
        return None
    try:
        from vk_api.audio import VkAudio
        _vk_audio = VkAudio(session)
        logger.info("VK Music provider initialised")
        return _vk_audio
    except ImportError:
        logger.warning("vk_api not installed — VK provider disabled")
    except Exception as e:
        logger.error("VK init failed: %s", e)
    return None


# _fmt_dur imported from bot.utils


def _response_items(response) -> list[dict]:
    """Extract audio items from VK responses across old/new shapes."""
    if not response:
        return []
    if isinstance(response, dict):
        items = response.get("items", [])
        return [it for it in items if isinstance(it, dict)]
    # Older VK API shapes were [count, item1, item2, ...].
    if isinstance(response, (list, tuple)):
        raw_items = response[1:] if response and isinstance(response[0], int) else response
        return [it for it in raw_items if isinstance(it, dict)]
    return []


def _track_to_result(tr: dict) -> dict | None:
    artist = (tr.get("artist") or "").strip()
    title = (tr.get("title") or "").strip()
    try:
        duration = int(tr.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    url = tr.get("url") or ""
    if not url or not artist or not title:
        return None
    if duration <= 0 or duration > settings.MAX_DURATION:
        return None

    album = tr.get("album") or {}
    thumb = album.get("thumb") if isinstance(album, dict) else {}
    thumb = thumb if isinstance(thumb, dict) else {}
    cover = thumb.get("photo_600") or thumb.get("photo_300") or thumb.get("photo_270") or None
    return {
        "video_id": f"vk_{tr.get('owner_id')}_{tr.get('id')}",
        "vk_url": url,
        "title": title,
        "uploader": artist,
        "duration": duration,
        "duration_fmt": _fmt_dur(duration),
        "source": "vk",
        "cover_url": cover,
    }


def _format_vk_results(tracks: list[dict], limit: int) -> list[dict]:
    results: list[dict] = []
    for tr in tracks:
        result = _track_to_result(tr)
        if result is None:
            continue
        results.append(result)
        if len(results) >= limit:
            break
    return results


def _search_vk_api_sync(query: str, limit: int) -> list[dict]:
    """Search via VK API directly, avoiding vk_api.audio web parser fragility."""
    session = _get_vk_session()
    if session is None:
        return []
    response = session.method(
        "audio.search",
        {
            "q": query,
            "count": min(limit + 10, 100),
            "auto_complete": 1,
            "sort": 2,
        },
    )
    return _response_items(response)


def _iter_playlists(obj):
    if isinstance(obj, dict):
        playlist = obj.get("playlist")
        if isinstance(playlist, dict):
            yield playlist
        playlists = obj.get("playlists")
        if isinstance(playlists, list):
            for item in playlists:
                yield from _iter_playlists(item)
        for value in obj.values():
            if isinstance(value, (dict, list)):
                yield from _iter_playlists(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_playlists(item)


def _search_vk_web_sync(query: str, limit: int) -> list[dict]:
    """Search via VK web audio endpoint with safe payload parsing.

    This replaces vk_api.audio.VkAudio.search for search because the upstream
    parser indexes payload[1][1] directly and crashes when VK returns an empty
    search section (`payload=[0, []]`).
    """
    audio = _get_vk_audio()
    if audio is None:
        return []
    from vk_api.audio import scrap_ids, scrap_tracks

    response = audio._vk.http.post(
        "https://vk.com/al_audio.php",
        data={
            "al": 1,
            "act": "section",
            "claim": 0,
            "is_layer": 0,
            "owner_id": audio.user_id,
            "section": "search",
            "q": query,
        },
    )
    try:
        payload = json.loads(response.text.replace("<!--", "")).get("payload")
    except Exception as e:
        logger.debug("VK web search JSON parse failed: %s", e)
        return []

    tracks: list[dict] = []
    for playlist in _iter_playlists(payload):
        ids = scrap_ids(playlist.get("list") or [])
        if not ids:
            continue
        tracks.extend(
            scrap_tracks(
                ids,
                audio.user_id,
                convert_m3u8_links=audio.convert_m3u8_links,
                http=audio._vk.http,
            )
        )
        if len(tracks) >= limit:
            break
    return tracks


def _search_vk_sync(query: str, limit: int) -> list[dict]:
    try:
        results = _format_vk_results(_search_vk_api_sync(query, limit), limit)
        if results:
            return results
    except Exception as e:
        logger.debug("VK direct API search failed, falling back to web search: %s", e)

    try:
        return _format_vk_results(_search_vk_web_sync(query, limit), limit)
    except Exception as e:
        logger.error("VK web search failed: %s", e)
        return []


async def search_vk(query: str, limit: int = 5) -> list[dict]:
    """Search VK Music. Returns [] if VK_TOKEN not configured or on any error."""
    if not settings.VK_TOKEN:
        return []
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_vk_pool, _search_vk_sync, query, limit)


async def download_vk(url: str, dest: Path) -> Path:
    """Fetch a direct VK MP3 URL and stream it to dest."""
    headers = {
        "User-Agent": (
            "VKAndroidApp/7.48-16291 "
            "(Android 11; SDK 30; x86_64; unknown Android SDK built for x86_64; ru; 1080x1920)"
        ),
    }
    staged_dest = stage_path_for(dest, suffix=".vk")
    try:
        async with get_session().get(
            url, headers=headers, timeout=aiohttp.ClientTimeout(total=90)
        ) as resp:
            resp.raise_for_status()
            with staged_dest.open("wb") as f:
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    f.write(chunk)
        return finalize_staged_file(staged_dest, dest)
    except Exception:
        cleanup_staged_files(staged_dest)
        raise
