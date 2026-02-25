"""VK Music Provider — search and download via vk_api.

Requires a Kate Mobile / VK Android token set via VK_TOKEN env var.
Falls back gracefully (returns []) if the library is not installed or
the token is missing / invalid.
"""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import aiohttp

from bot.config import settings

logger = logging.getLogger(__name__)

_vk_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="vk")
_vk_audio: object = None   # cached VkAudio instance


def _get_vk_audio():
    global _vk_audio
    if _vk_audio is not None:
        return _vk_audio
    if not settings.VK_TOKEN:
        return None
    try:
        import vk_api
        from vk_api import VkAudio
        session = vk_api.VkApi(token=settings.VK_TOKEN)
        _vk_audio = VkAudio(session)
        logger.info("VK Music provider initialised")
        return _vk_audio
    except ImportError:
        logger.warning("vk_api not installed — VK provider disabled")
    except Exception as e:
        logger.error("VK init failed: %s", e)
    return None


def _fmt_dur(s: int) -> str:
    m, sec = divmod(s, 60)
    return f"{m}:{sec:02d}"


def _search_vk_sync(query: str, limit: int) -> list[dict]:
    audio = _get_vk_audio()
    if audio is None:
        return []
    try:
        tracks = audio.search(q=query, count=min(limit + 10, 100))
        results: list[dict] = []
        for tr in tracks:
            artist = (tr.get("artist") or "").strip()
            title = (tr.get("title") or "").strip()
            duration = int(tr.get("duration") or 0)
            url = tr.get("url") or ""
            if not url or not artist or not title:
                continue
            if duration <= 0 or duration > settings.MAX_DURATION:
                continue
            results.append({
                "video_id": f"vk_{tr.get('owner_id')}_{tr.get('id')}",
                "vk_url": url,
                "title": title,
                "uploader": artist,
                "duration": duration,
                "duration_fmt": _fmt_dur(duration),
                "source": "vk",
            })
            if len(results) >= limit:
                break
        return results
    except Exception as e:
        logger.error("VK search failed: %s", e)
        return []


async def search_vk(query: str, limit: int = 5) -> list[dict]:
    """Search VK Music. Returns [] if VK_TOKEN not configured or on any error."""
    if not settings.VK_TOKEN:
        return []
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_vk_pool, _search_vk_sync, query, limit)


async def download_vk(url: str, dest: Path) -> Path:
    """Fetch a direct VK MP3 URL and write it to dest."""
    headers = {
        "User-Agent": (
            "VKAndroidApp/7.48-16291 "
            "(Android 11; SDK 30; x86_64; unknown Android SDK built for x86_64; ru; 1080x1920)"
        ),
    }
    async with aiohttp.ClientSession() as sess:
        async with sess.get(
            url, headers=headers, timeout=aiohttp.ClientTimeout(total=90)
        ) as resp:
            resp.raise_for_status()
            dest.write_bytes(await resp.read())
    return dest
