"""Telegram CDN Cache — upload tracks to a private channel for instant playback.

Uses a private Telegram channel as persistent cloud storage:
- After downloading a track, upload MP3 to the channel → store file_id in DB
- When streaming, if file is missing on disk but has file_id → download from Telegram CDN
- Telegram CDN is globally distributed, fast, and free

Requires CACHE_CHANNEL_ID env var (private channel ID, e.g. -100xxxx).
"""
import asyncio
import logging
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

from bot.config import settings

logger = logging.getLogger(__name__)

_bot: Bot | None = None
_upload_semaphore = asyncio.Semaphore(3)  # max 3 concurrent uploads


def _get_bot() -> Bot | None:
    """Lazy-init a lightweight Bot instance for cache operations."""
    global _bot
    if _bot is not None:
        return _bot
    if not settings.BOT_TOKEN:
        return None
    _bot = Bot(token=settings.BOT_TOKEN)
    return _bot


async def upload_to_cache(
    mp3_path: Path,
    source_id: str,
    title: str | None = None,
    artist: str | None = None,
    duration: int | None = None,
) -> str | None:
    """Upload MP3 to cache channel, return file_id. Returns None on failure."""
    if not settings.CACHE_CHANNEL_ID:
        return None
    bot = _get_bot()
    if not bot:
        return None
    if not mp3_path.exists() or mp3_path.stat().st_size < 10 * 1024:
        return None

    async with _upload_semaphore:
        try:
            caption = f"{artist} — {title}" if artist and title else (title or source_id)
            msg = await bot.send_audio(
                chat_id=settings.CACHE_CHANNEL_ID,
                audio=FSInputFile(mp3_path),
                title=title or "Unknown",
                performer=artist or "Unknown",
                duration=duration,
                caption=caption[:200],
            )
            file_id = msg.audio.file_id if msg.audio else None
            if file_id:
                # Save file_id to DB
                await _save_file_id(source_id, file_id)
                # Save to Redis cache too
                try:
                    from bot.services.cache import cache
                    await cache.set_file_id(source_id, file_id)
                except Exception:
                    pass
                logger.info("Cached %s to Telegram CDN (file_id=%s...)", source_id, file_id[:20])
            return file_id
        except Exception as e:
            logger.debug("Cache upload failed for %s: %s", source_id, e)
            return None


async def download_from_cache(file_id: str, dest_path: Path) -> Path | None:
    """Download file from Telegram CDN by file_id. Returns path on success."""
    bot = _get_bot()
    if not bot:
        return None
    try:
        file = await bot.get_file(file_id)
        if not file.file_path:
            return None
        await bot.download_file(file.file_path, destination=dest_path)
        if dest_path.exists() and dest_path.stat().st_size > 10 * 1024:
            logger.info("Restored %s from Telegram CDN (%d KB)", dest_path.name, dest_path.stat().st_size // 1024)
            return dest_path
        return None
    except Exception as e:
        logger.debug("CDN download failed for file_id %s...: %s", file_id[:20], e)
        return None


async def get_file_id(source_id: str) -> str | None:
    """Get file_id from Redis cache or DB."""
    # Try Redis first (fast)
    try:
        from bot.services.cache import cache
        fid = await cache.get_file_id(source_id)
        if fid:
            return fid
    except Exception:
        pass
    # Fallback to DB
    try:
        from bot.models.base import async_session
        from bot.models.track import Track
        from sqlalchemy import select
        async with async_session() as session:
            row = (await session.execute(
                select(Track.file_id).where(Track.source_id == source_id)
            )).scalar_one_or_none()
            if row:
                # Warm Redis cache
                try:
                    from bot.services.cache import cache as _c
                    await _c.set_file_id(source_id, row)
                except Exception:
                    pass
                return row
    except Exception:
        pass
    return None


async def _save_file_id(source_id: str, file_id: str) -> None:
    """Persist file_id to DB track record."""
    try:
        from bot.models.base import async_session
        from bot.models.track import Track
        async with async_session() as session:
            await session.execute(
                Track.__table__.update()
                .where(Track.source_id == source_id)
                .values(file_id=file_id)
            )
            await session.commit()
    except Exception as e:
        logger.debug("_save_file_id failed for %s: %s", source_id, e)


def schedule_upload(mp3_path: Path, source_id: str, title: str | None = None,
                    artist: str | None = None, duration: int | None = None) -> None:
    """Fire-and-forget upload to cache channel."""
    if not settings.CACHE_CHANNEL_ID:
        return
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(
            upload_to_cache(mp3_path, source_id, title, artist, duration),
        )
    except RuntimeError:
        pass  # no running loop
