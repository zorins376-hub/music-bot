"""Chart track prefetcher — background download of all chart tracks.

Prefetches all tracks from charts (Shazam, YouTube, VK, RusRadio, Europa)
to local disk at bot startup and periodically. This provides:
  - Instant playback for popular tracks (no download wait)
  - Reduced external API load during peak usage
  - Better user experience in groups

Estimated size: ~300 tracks × 5MB = ~1.5GB
"""

import asyncio
import logging
import re
import time
from pathlib import Path

from bot.config import settings

logger = logging.getLogger(__name__)

# How many tracks to download in parallel
_PREFETCH_CONCURRENCY = 3

# Interval between full prefetch runs (1 hour)
_PREFETCH_INTERVAL = 3600

# Minimum file size to consider track already cached (10KB)
_MIN_CACHED_SIZE = 10 * 1024

# YouTube video ID pattern (exclude ym_ Yandex prefix)
_YT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")

# Permanently failed video IDs (age-restricted, geo-blocked, etc.)
# Maps video_id -> timestamp when it was blacklisted
# Entries expire after 24 hours in case the issue is resolved
_PERMANENT_FAILURES: dict[str, float] = {}
_FAILURE_TTL = 86400  # 24 hours

# Error messages that indicate permanent failures (no point retrying)
_PERMANENT_ERROR_PATTERNS = [
    "Sign in to confirm your age",
    "age-restricted",
    "This video is not available",
    "Video unavailable",
    "Private video",
    "been removed",
    "copyright",
    "blocked",
    "geo restriction",
]

def _is_youtube_id(video_id: str) -> bool:
    """Check if ID is a valid YouTube video ID (not Yandex)."""
    return bool(
        _YT_ID_PATTERN.match(video_id)
        and not video_id.startswith("ym_")
    )


async def prefetch_chart_tracks(
    bitrate: int = 192,
    max_per_chart: int = 100,
) -> dict[str, int]:
    """Download all chart tracks to local cache.
    
    Returns dict with counts: {"downloaded": N, "skipped": N, "failed": N}
    """
    from bot.handlers.charts import _get_chart, _CHART_FETCHERS
    from bot.services.download_manager import download_manager

    stats = {"downloaded": 0, "skipped": 0, "failed": 0}
    semaphore = asyncio.Semaphore(_PREFETCH_CONCURRENCY)
    
    async def download_one(video_id: str) -> bool:
        """Download single track. Returns True if downloaded, False if skipped/failed."""
        # Skip permanently failed videos (age-restricted, geo-blocked, etc.)
        if video_id in _PERMANENT_FAILURES:
            if time.time() - _PERMANENT_FAILURES[video_id] < _FAILURE_TTL:
                return False  # still blacklisted
            else:
                del _PERMANENT_FAILURES[video_id]  # expired, retry

        mp3_path = settings.DOWNLOAD_DIR / f"{video_id}.mp3"

        # Skip if already cached
        if mp3_path.exists() and mp3_path.stat().st_size > _MIN_CACHED_SIZE:
            return False

        async with semaphore:
            try:
                await download_manager.download(video_id, bitrate=bitrate)
                return True
            except Exception as e:
                err_msg = str(e)
                # Check if this is a permanent failure
                if any(pattern.lower() in err_msg.lower() for pattern in _PERMANENT_ERROR_PATTERNS):
                    _PERMANENT_FAILURES[video_id] = time.time()
                    logger.info("Prefetch: permanently skipping %s (reason: %s)", video_id, err_msg[:100])
                else:
                    logger.debug("Prefetch failed for %s: %s", video_id, e)
                stats["failed"] += 1
                return False

    # Collect all unique video IDs from all charts
    all_video_ids: set[str] = set()
    
    for source in _CHART_FETCHERS:
        try:
            tracks = await _get_chart(source)
            if not tracks:
                continue
            
            for track in tracks[:max_per_chart]:
                video_id = track.get("video_id", "").strip()
                # Only YouTube IDs (skip Yandex which needs special handling)
                if video_id and _is_youtube_id(video_id):
                    all_video_ids.add(video_id)
                    
        except Exception as e:
            logger.warning("Prefetch: failed to get chart %s: %s", source, e)
    
    if not all_video_ids:
        logger.info("Prefetch: no tracks to download")
        return stats
    
    logger.info("Prefetch: starting download of %d unique tracks", len(all_video_ids))
    
    # Download all tracks concurrently (limited by semaphore)
    tasks = [download_one(vid) for vid in all_video_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    for r in results:
        if r is True:
            stats["downloaded"] += 1
        elif r is False:
            stats["skipped"] += 1
        # Exceptions already counted in download_one
    
    logger.info(
        "Prefetch complete: %d downloaded, %d skipped (cached), %d failed",
        stats["downloaded"], stats["skipped"], stats["failed"]
    )
    
    return stats


async def get_cache_stats() -> dict:
    """Get current cache statistics."""
    download_dir: Path = settings.DOWNLOAD_DIR
    
    if not download_dir.exists():
        return {"files": 0, "size_mb": 0}
    
    files = list(download_dir.glob("*.mp3"))
    total_size = sum(f.stat().st_size for f in files)
    
    return {
        "files": len(files),
        "size_mb": round(total_size / (1024 * 1024), 1),
    }


async def _prefetch_loop() -> None:
    """Background loop that runs prefetch periodically."""
    while True:
        try:
            await prefetch_chart_tracks()
        except Exception as e:
            logger.error("Prefetch loop error: %s", e)
        
        await asyncio.sleep(_PREFETCH_INTERVAL)


_prefetch_task: asyncio.Task | None = None


async def start_prefetch_scheduler() -> None:
    """Start the background prefetch scheduler."""
    global _prefetch_task
    
    if _prefetch_task is not None:
        return
    
    logger.info("Starting chart prefetch scheduler (interval: %ds)", _PREFETCH_INTERVAL)
    _prefetch_task = asyncio.create_task(_prefetch_loop())


async def stop_prefetch_scheduler() -> None:
    """Stop the background prefetch scheduler."""
    global _prefetch_task
    
    if _prefetch_task is not None:
        _prefetch_task.cancel()
        try:
            await _prefetch_task
        except asyncio.CancelledError:
            pass
        _prefetch_task = None
