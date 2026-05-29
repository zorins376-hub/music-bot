"""Patch chart_prefetcher.py — much gentler on YouTube to avoid 429 rate-limits."""
import sys
from pathlib import Path

TARGET = Path("/root/music-bot/bot/services/chart_prefetcher.py")
src = TARGET.read_text()
orig = src

# 1) Concurrency 3 → 1 (sequential YouTube downloads = no concurrent 429s)
src = src.replace(
    "_PREFETCH_CONCURRENCY = 3",
    "_PREFETCH_CONCURRENCY = 1",
    1,
)

# 2) Interval 1h → 6h (charts barely change in 6h)
src = src.replace(
    "_PREFETCH_INTERVAL = 3600",
    "_PREFETCH_INTERVAL = 21600  # 6h — was 1h, reduced to lower YT rate-limit pressure",
    1,
)

# 3) Reduce YouTube tracks per chart from 100 → 30
OLD_DEF = "async def prefetch_chart_tracks(\n    bitrate: int = 192,\n    max_per_chart: int = 100,\n) -> dict[str, int]:"
NEW_DEF = "async def prefetch_chart_tracks(\n    bitrate: int = 192,\n    max_per_chart: int = 30,\n) -> dict[str, int]:"
src = src.replace(OLD_DEF, NEW_DEF, 1)

# 4) Use downloader's _is_permanently_failed (shared cache) in addition to local
#    Insert check right at the start of download_one
OLD_DL_ONE = '''    async def download_one(video_id: str) -> bool:
        """Download single track. Returns True if downloaded, False if skipped/failed."""
        # Skip permanently failed videos (age-restricted, geo-blocked, etc.)
        if video_id in _PERMANENT_FAILURES:'''
NEW_DL_ONE = '''    # Track consecutive YouTube failures — if too many in a row, abort YouTube prefetch
    yt_fail_streak = {"count": 0}

    async def download_one(video_id: str) -> bool:
        """Download single track. Returns True if downloaded, False if skipped/failed."""
        # Skip if downloader marked it permanently failed (shared cache)
        try:
            from bot.services.downloader import _is_permanently_failed as _shared_pf
            if _shared_pf(video_id):
                return False
        except Exception:
            pass
        # Skip permanently failed videos (age-restricted, geo-blocked, etc.)
        if video_id in _PERMANENT_FAILURES:'''
src = src.replace(OLD_DL_ONE, NEW_DL_ONE, 1)

# 5) Add fail-streak abort + 1-second delay between downloads
OLD_DOWNLOAD_BLOCK = """        async with semaphore:
            try:
                await download_manager.download(video_id, bitrate=bitrate)"""
NEW_DOWNLOAD_BLOCK = """        # If we've hit many YT failures in a row, give up on YouTube prefetch this round
        if yt_fail_streak["count"] >= 8:
            return False
        async with semaphore:
            # Throttle: 2-second delay between YouTube downloads to be gentle on rate limits
            await asyncio.sleep(2.0)
            try:
                await download_manager.download(video_id, bitrate=bitrate)
                yt_fail_streak["count"] = 0  # reset on success"""
src = src.replace(OLD_DOWNLOAD_BLOCK, NEW_DOWNLOAD_BLOCK, 1)

# 6) Increment fail streak on failure
OLD_FAIL = """                else:
                    logger.debug("Prefetch failed for %s: %s", video_id, e)
                stats["failed"] += 1
                return False

    async def download_one_ym(video_id: str) -> bool:"""
NEW_FAIL = """                else:
                    logger.debug("Prefetch failed for %s: %s", video_id, e)
                    # Treat 429 / network errors as fail-streak hits
                    if "429" in err_msg or "Too Many Requests" in err_msg or "timeout" in err_msg.lower():
                        yt_fail_streak["count"] += 1
                        if yt_fail_streak["count"] >= 8:
                            logger.warning("Prefetch: YT fail-streak limit (8) reached — aborting YT prefetch this round")
                stats["failed"] += 1
                return False

    async def download_one_ym(video_id: str) -> bool:"""
src = src.replace(OLD_FAIL, NEW_FAIL, 1)

# Verify syntax
import ast
try:
    ast.parse(src)
except SyntaxError as e:
    print(f"FATAL syntax error at line {e.lineno}: {e.msg}")
    sys.exit(1)

bak = TARGET.with_suffix(".py.bak")
bak.write_text(orig)
TARGET.write_text(src)

print(f"Patched: {TARGET}")
print(f"Backup:  {bak}")
print(f"  - concurrency: 3 -> 1 (sequential)")
print(f"  - interval:    1h -> 6h")
print(f"  - max per chart: 100 -> 30")
print(f"  - shared perm-failed cache check")
print(f"  - 2s delay between YT downloads")
print(f"  - abort YT prefetch after 8 consecutive failures")
print(f"Restart: docker compose restart bot")
