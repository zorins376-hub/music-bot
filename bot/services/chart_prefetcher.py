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

# Interval between full prefetch runs. Now that warming is Yandex-first (never
# rate-limited), it no longer competes with organic YouTube downloads, so we can
# run more often to fill file_ids faster. 3h keeps Yandex load gentle.
_PREFETCH_INTERVAL = 3 * 3600

# Minimum file size to consider track already cached (10KB)
_MIN_CACHED_SIZE = 10 * 1024

# YouTube video ID pattern
_YT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")

# Yandex Music video ID pattern (ym_<digits>)
_YM_ID_PATTERN = re.compile(r"^ym_\d+$")

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
    """Check if ID is a valid YouTube video ID."""
    return bool(
        _YT_ID_PATTERN.match(video_id)
        and not video_id.startswith("ym_")
    )


def _is_yandex_id(video_id: str) -> bool:
    """Check if ID is a Yandex Music track (ym_<digits>)."""
    return bool(_YM_ID_PATTERN.match(video_id))


async def prefetch_chart_tracks(
    bitrate: int = 192,
    max_per_chart: int = 150,
) -> dict[str, int]:
    """Warm chart tracks into the Telegram-CDN file_id cache — Yandex-first.

    For every chart track we resolve "Artist Title" on Yandex (which is never
    rate-limited) and download from there, falling back to the chart's YouTube id
    only when Yandex has no match AND YouTube is healthy. This fills file_ids fast
    without burning the rate-limited YouTube/WARP quota that organic user downloads
    need. Deduped by query so the same song isn't resolved twice across charts.

    Returns dict with counts: {"downloaded": N, "skipped": N, "failed": N}
    """
    from bot.handlers.charts import _get_chart, _CHART_FETCHERS
    from bot.services.download_manager import download_manager
    from bot.services.yandex_provider import download_yandex, search_yandex

    stats = {"downloaded": 0, "skipped": 0, "failed": 0}
    semaphore = asyncio.Semaphore(_PREFETCH_CONCURRENCY)

    yt_disabled = False
    try:
        from bot.services.provider_health import is_provider_disabled
        yt_disabled = is_provider_disabled("youtube")
    except Exception:
        pass

    async def _upload_if_new(video_id: str, path: Path) -> None:
        try:
            from bot.services.telegram_cache import get_file_id as _get_cache_fid, schedule_upload
            if path.exists() and not await _get_cache_fid(video_id):
                schedule_upload(path, video_id)
        except Exception:
            logger.debug("schedule_upload failed for %s", video_id, exc_info=True)

    async def _dl_yandex(ym_id: int) -> bool:
        """True=downloaded, False=already cached; raises on error."""
        vid = f"ym_{ym_id}"
        mp3 = settings.DOWNLOAD_DIR / f"{vid}.mp3"
        if mp3.exists() and mp3.stat().st_size > _MIN_CACHED_SIZE:
            return False
        await asyncio.wait_for(download_yandex(ym_id, mp3, bitrate), timeout=120)
        await _upload_if_new(vid, mp3)
        return True

    async def _dl_youtube(video_id: str) -> bool:
        """True=downloaded, False=already cached; raises on error (fallback only)."""
        if video_id in _PERMANENT_FAILURES:
            if time.time() - _PERMANENT_FAILURES[video_id] < _FAILURE_TTL:
                return False
            del _PERMANENT_FAILURES[video_id]
        mp3 = settings.DOWNLOAD_DIR / f"{video_id}.mp3"
        if mp3.exists() and mp3.stat().st_size > _MIN_CACHED_SIZE:
            return False
        try:
            await download_manager.download(video_id, bitrate=bitrate)
            await _upload_if_new(video_id, settings.DOWNLOAD_DIR / f"{video_id}.mp3")
            return True
        except Exception as e:
            if any(p.lower() in str(e).lower() for p in _PERMANENT_ERROR_PATTERNS):
                _PERMANENT_FAILURES[video_id] = time.time()
                logger.info("Prefetch: permanently skipping %s (%s)", video_id, str(e)[:80])
            raise

    async def warm_one(query: str, video_id: str):
        """True=downloaded, False=already cached, None=failed."""
        async with semaphore:
            # 1) Yandex first — a ym_ chart id resolves directly; otherwise search.
            ym_id: int | None = None
            if _is_yandex_id(video_id):
                try:
                    ym_id = int(video_id[3:])
                except Exception:
                    ym_id = None
            if ym_id is None and query:
                try:
                    r = await asyncio.wait_for(search_yandex(query, limit=1), timeout=10)
                    if r and r[0].get("ym_track_id"):
                        ym_id = int(r[0]["ym_track_id"])
                except Exception:
                    ym_id = None
            if ym_id is not None:
                try:
                    return await _dl_yandex(ym_id)
                except Exception as e:
                    logger.debug("Prefetch(ym) failed for %r: %s", query[:50], e)
            # 2) Fallback: YouTube (only when healthy and it's a real yt id).
            if video_id and _is_youtube_id(video_id) and not yt_disabled:
                try:
                    return await _dl_youtube(video_id)
                except Exception as e:
                    logger.debug("Prefetch(yt) failed for %s: %s", video_id, e)
            return None

    # Collect (query, video_id) from all charts, deduped by query.
    seen_q: set[str] = set()
    items: list[tuple[str, str]] = []
    for source in _CHART_FETCHERS:
        try:
            tracks = await _get_chart(source)
        except Exception as e:
            logger.warning("Prefetch: failed to get chart %s: %s", source, e)
            continue
        for track in (tracks or [])[:max_per_chart]:
            artist = (track.get("uploader") or track.get("artist") or "").strip()
            title = (track.get("title") or "").strip()
            query = f"{artist} {title}".strip()
            video_id = (track.get("video_id") or "").strip()
            key = query.lower()
            if len(query) < 3 or key in seen_q:
                continue
            seen_q.add(key)
            items.append((query, video_id))

    # CIS per-country Apple charts — locally-popular tracks; no video_id, so they
    # resolve + download via Yandex (never rate-limited).
    try:
        from bot.handlers.charts import cis_chart_tracks
        for track in await cis_chart_tracks(per_country=max_per_chart):
            artist = (track.get("artist") or track.get("uploader") or "").strip()
            title = (track.get("title") or "").strip()
            query = f"{artist} {title}".strip()
            key = query.lower()
            if len(query) < 3 or key in seen_q:
                continue
            seen_q.add(key)
            items.append((query, ""))
    except Exception as e:
        logger.warning("Prefetch: CIS chart fetch failed: %s", e)

    if not items:
        logger.info("Prefetch: no tracks to warm")
        return stats

    logger.info(
        "Prefetch: warming %d chart tracks (Yandex-first, yt_fallback=%s)",
        len(items), "off" if yt_disabled else "on",
    )

    results = await asyncio.gather(*[warm_one(q, v) for q, v in items], return_exceptions=True)
    for r in results:
        if r is True:
            stats["downloaded"] += 1
        elif r is False:
            stats["skipped"] += 1
        else:  # None or an exception from gather
            stats["failed"] += 1

    logger.info(
        "Prefetch complete: %d downloaded, %d skipped, %d failed (of %d)",
        stats["downloaded"], stats["skipped"], stats["failed"], len(items),
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
