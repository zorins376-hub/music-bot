"""Disable YouTube prefetch entirely — it just hammers rate limits with 429 errors."""
import sys
from pathlib import Path

TARGET = Path("/root/music-bot/bot/services/chart_prefetcher.py")
src = TARGET.read_text()
orig = src

# Skip YouTube tracks in prefetch by clearing the yt_video_ids set
OLD = '''    # Download all tracks concurrently (limited by semaphore)
    tasks = [download_one(vid) for vid in yt_video_ids]
    tasks += [download_one_ym(vid) for vid in ym_video_ids]'''

NEW = '''    # YouTube prefetch is disabled: too many 429 rate-limit errors and content
    # is generally unavailable to yt-dlp without cookies. Only Yandex tracks are
    # reliable enough for bulk prefetch.
    logger.info("Prefetch: skipping %d YouTube tracks (disabled), keeping %d Yandex",
                len(yt_video_ids), len(ym_video_ids))
    yt_video_ids = set()  # disable YouTube prefetch
    # Download Yandex tracks concurrently (limited by semaphore)
    tasks = [download_one(vid) for vid in yt_video_ids]
    tasks += [download_one_ym(vid) for vid in ym_video_ids]'''

if NEW in src:
    print("Already applied — skipping")
    sys.exit(0)

if OLD not in src:
    print(f"FATAL: anchor not found")
    sys.exit(1)

src = src.replace(OLD, NEW, 1)

import ast
ast.parse(src)  # raises if broken

bak = TARGET.with_suffix(".py.bak2")
bak.write_text(orig)
TARGET.write_text(src)
print(f"Patched {TARGET}")
print(f"Backup: {bak}")
print("YouTube prefetch is now DISABLED. Only Yandex tracks will be prefetched.")
