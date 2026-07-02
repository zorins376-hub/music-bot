"""Auto-cleanup of /app/downloads — removes orphaned files periodically.

Files that weren't cleaned up after a download (timeouts, crashes) accumulate
over time. This scheduler removes files older than _MAX_AGE_SEC every 15 min.
"""
import asyncio
import logging
import time
from pathlib import Path

from bot.config import settings

logger = logging.getLogger(__name__)

_MAX_AGE_SEC = 30 * 60   # 30 minutes — long enough for slow uploads
_INTERVAL_SEC = 15 * 60  # 15 minutes


def _cleanup_once() -> int:
    """Remove old files from DOWNLOAD_DIR. Returns count of removed files."""
    download_dir = settings.DOWNLOAD_DIR
    if not download_dir.exists():
        return 0
    now = time.time()
    removed = 0
    bytes_freed = 0
    for f in download_dir.iterdir():
        try:
            if not f.is_file():
                continue
            age = now - f.stat().st_mtime
            if age > _MAX_AGE_SEC:
                size = f.stat().st_size
                f.unlink()
                removed += 1
                bytes_freed += size
        except Exception:
            logger.debug("cleanup_once: failed to remove %s", f, exc_info=True)
    if removed:
        logger.info("downloads_cleanup: removed %d files, freed %.1f MB",
                    removed, bytes_freed / (1024 * 1024))
    return removed


async def start_downloads_cleanup_scheduler() -> None:
    """Background task: periodically remove orphaned downloads."""
    async def _loop():
        await asyncio.sleep(60)  # initial delay
        while True:
            try:
                await asyncio.to_thread(_cleanup_once)
            except Exception as e:
                logger.warning("downloads_cleanup error: %s", e)
            await asyncio.sleep(_INTERVAL_SEC)

    asyncio.create_task(_loop())
    logger.info("downloads_cleanup scheduler started (interval=%ds, max_age=%ds)",
                _INTERVAL_SEC, _MAX_AGE_SEC)
