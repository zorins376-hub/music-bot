"""
file_id_heal.py — self-healing for dead Telegram file_ids.

A Telegram file_id is tied to the Bot API instance/context that issued it. When
that context changes (e.g. the local Bot API server or its identity changes),
previously-cached file_ids start failing to send with
"Bad Request: invalid remote file identifier". Delivery paths use `send_or_heal`
so that when a cached file_id is dead, we purge THAT ONE entry (Redis + Postgres)
and fall through to a fresh download — which re-caches a valid file_id. The cache
thus self-heals one track at a time, on demand, with no bulk operation.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def is_dead_file_id_error(exc: Exception) -> bool:
    """True only for the specific 'this file_id is no longer usable' errors —
    not for unrelated failures (too big, chat not found, flood, etc.)."""
    m = str(exc).lower()
    return (
        "invalid remote file identifier" in m
        or "invalid file_id" in m
        or "wrong file identifier" in m
        or ("file reference" in m and "expired" in m)
    )


async def drop_dead_file_id(video_id: str, bitrate: int | None = None) -> None:
    """Purge a single dead file_id from Redis (fid:*) and Postgres (tracks.file_id)."""
    if not video_id:
        return
    from bot.services.cache import cache
    try:
        if bitrate:
            await cache.redis.delete(f"fid:{video_id}:{bitrate}")
        else:
            for br in (128, 192, 320):
                await cache.redis.delete(f"fid:{video_id}:{br}")
    except Exception:
        logger.debug("drop_dead_file_id: redis delete failed for %s", video_id, exc_info=True)
    try:
        from sqlalchemy import update
        from bot.models.base import async_session
        from bot.models.track import Track
        async with async_session() as s:
            await s.execute(update(Track).where(Track.source_id == video_id).values(file_id=None))
            await s.commit()
    except Exception:
        logger.debug("drop_dead_file_id: pg update failed for %s", video_id, exc_info=True)


async def send_or_heal(send_factory, video_id: str, bitrate: int | None = None):
    """Await a send-by-file_id coroutine produced by `send_factory`. If the file_id
    is dead, purge it and return None so the caller falls through to a fresh
    download (which re-caches a valid file_id). Any other error propagates."""
    from aiogram.exceptions import TelegramBadRequest
    try:
        return await send_factory()
    except TelegramBadRequest as e:
        if is_dead_file_id_error(e):
            await drop_dead_file_id(video_id, bitrate)
            logger.warning("file_id_heal: purged dead file_id for %s (%s); re-downloading", video_id, e)
            return None
        raise
