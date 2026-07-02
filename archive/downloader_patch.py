"""Reduce log noise: demote expected YouTube restrictions from ERROR to WARNING."""
import sys
from pathlib import Path

TARGET = Path("/root/music-bot/bot/services/downloader.py")
src = TARGET.read_text()
orig = src

# 1. Add "This content isn't available" patterns (both apostrophe types)
OLD_PATTERNS = '''_EXPECTED_RESTRICTION_PATTERNS = [
    "Sign in to confirm your age",
    "Video unavailable",
    "not available in your country",
    "This video is private",
    "This video is not available",
    "has been removed",
    "Requested format is not available",
    "does not look like a Netscape format cookies file",'''

NEW_PATTERNS = '''_EXPECTED_RESTRICTION_PATTERNS = [
    "Sign in to confirm your age",
    "Video unavailable",
    "not available in your country",
    "This video is private",
    "This video is not available",
    "This content isn't available",
    "This content isn’t available",  # typographic apostrophe variant
    "Permanently failed (cached)",
    "has been removed",
    "Requested format is not available",
    "does not look like a Netscape format cookies file",'''

if NEW_PATTERNS not in src:
    if OLD_PATTERNS not in src:
        print("FATAL: pattern block not found")
        sys.exit(1)
    src = src.replace(OLD_PATTERNS, NEW_PATTERNS, 1)
    print("+ Added 3 new patterns to expected-restriction list")

# 2. Demote "DEBUG list-formats failed" from ERROR to DEBUG (it's a diagnostic helper)
src = src.replace(
    'logger.error("DEBUG list-formats failed for %s: %s", video_id, e)',
    'logger.debug("DEBUG list-formats failed for %s: %s", video_id, e)',
    1,
)
print("+ Demoted 'DEBUG list-formats failed' to debug level")

# 3. Skip _list_formats_debug call for expected restrictions (saves another whole yt-dlp call)
OLD_LIST_FMT = """        else:
            logger.error("Download failed for %s: %s", video_id, e)
            _list_formats_debug(video_id)
        raise"""
NEW_LIST_FMT = """        else:
            logger.error("Download failed for %s: %s", video_id, e)
            # Only call _list_formats_debug for unexpected errors (saves another yt-dlp roundtrip)
            if not _is_expected_restriction_error(e):
                _list_formats_debug(video_id)
        raise"""

if OLD_LIST_FMT in src:
    src = src.replace(OLD_LIST_FMT, NEW_LIST_FMT, 1)
    print("+ Skip _list_formats_debug for expected restrictions")

# Verify and save
import ast
ast.parse(src)

bak = TARGET.with_suffix(".py.bak")
bak.write_text(orig)
TARGET.write_text(src)
print(f"Patched {TARGET}")
print(f"Backup: {bak}")
