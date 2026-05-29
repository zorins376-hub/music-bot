"""Add pre-flight permanently-failed check + auto-replacement in handle_track_select."""
import sys
from pathlib import Path

TARGET = Path("/root/music-bot/bot/handlers/search.py")
src = TARGET.read_text()
orig = src

# Inject pre-flight check right before the download lock acquisition
OLD = """    if not await _acquire_download_lock(user.id, video_id):
        return

    default_br = int(await _get_bot_setting("default_bitrate", "192"))"""

NEW = '''    # Pre-flight: if selected track is permanently failed, swap for a fresh YouTube result
    try:
        from bot.services.downloader import _is_permanently_failed as _pf
        if video_id and _pf(video_id):
            logger.info("Track %s is perm-failed — searching fresh YouTube alternative", video_id)
            _retry_q = f"{track_info.get('uploader', '')} {track_info.get('title', '')}".strip()
            if _retry_q:
                try:
                    _alt_tracks = await search_tracks(_retry_q, max_results=5, source="youtube")
                    for _cand in _alt_tracks:
                        _cvid = _cand.get("video_id", "")
                        if _cvid and not _pf(_cvid):
                            logger.info("Pre-flight: swapped perm-failed %s → %s", video_id, _cvid)
                            track_info = _cand
                            video_id = _cvid
                            _share_q = f"{track_info.get('uploader', '')} - {track_info.get('title', '')}"
                            break
                except Exception as _swap_err:
                    logger.debug("Pre-flight swap failed: %s", _swap_err)
    except Exception:
        pass

    if not await _acquire_download_lock(user.id, video_id):
        return

    default_br = int(await _get_bot_setting("default_bitrate", "192"))'''

if NEW in src:
    print("Already applied")
    sys.exit(0)
if OLD not in src:
    print("FATAL: anchor not found")
    sys.exit(1)

src = src.replace(OLD, NEW, 1)

# Also: enhance the DM auto-retry fallback — when source is YouTube/Spotify and
# we get a YouTube error, do a FRESH search instead of just retry on same query.
# This is the "Auto-retry with a different source" block — make it work for YT too.
OLD_RETRY = '''            _err_lower = err_msg.lower()
            _is_expected_err = any(p in _err_lower for p in (
                "permanently failed", "video unavailable",
                "this content isn", "this video is", "has been removed",
                "sign in to confirm your age", "geo restriction",
            ))
            if _is_expected_err:
                logger.warning("Download error for %s (expected): %s", video_id, err_msg)
            else:
                logger.error("Download error for %s: %s", video_id, err_msg)
            # C-07: Auto-retry with YouTube only if the original source was not YouTube,
            # AND the original error is not already a YouTube error (avoid double-retry)
            failed_source = track_info.get("source", "youtube")
            retry_query = f"{track_info.get('uploader', '')} {track_info.get('title', '')}".strip()
            _already_yt_err = "youtube" in err_msg.lower() or "ytdl" in err_msg.lower()
            if retry_query and failed_source != "youtube" and not _already_yt_err:
                try:
                    await status.edit_text(t(lang, "searching") + "...")
                    alt_results = await search_tracks(retry_query, max_results=1, source="youtube")'''

NEW_RETRY = '''            _err_lower = err_msg.lower()
            _is_expected_err = any(p in _err_lower for p in (
                "permanently failed", "video unavailable",
                "this content isn", "this video is", "has been removed",
                "sign in to confirm your age", "geo restriction",
            ))
            if _is_expected_err:
                logger.warning("Download error for %s (expected): %s", video_id, err_msg)
            else:
                logger.error("Download error for %s: %s", video_id, err_msg)
            # Auto-retry: search for OTHER YouTube candidates (not the failed one) and try them
            failed_source = track_info.get("source", "youtube")
            retry_query = f"{track_info.get('uploader', '')} {track_info.get('title', '')}".strip()
            if retry_query:
                try:
                    from bot.services.downloader import _is_permanently_failed as _pf_retry
                    await status.edit_text(t(lang, "searching") + "...")
                    alt_results = await search_tracks(retry_query, max_results=5, source="youtube")
                    # Pick the first candidate that is NOT the failed one and NOT perm-failed
                    alt_results = [r for r in alt_results
                                   if r.get("video_id") != video_id
                                   and not _pf_retry(r.get("video_id", ""))]'''

if NEW_RETRY not in src:
    if OLD_RETRY not in src:
        print("WARN: retry block not found — skipping that fix")
    else:
        src = src.replace(OLD_RETRY, NEW_RETRY, 1)
        print("+ Enhanced DM auto-retry: now searches for ANY non-failed YT candidate")

# Verify
import ast
ast.parse(src)

bak = TARGET.with_suffix(".py.bak4")
bak.write_text(orig)
TARGET.write_text(src)

print(f"\nPatched: {TARGET}")
print(f"Backup:  {bak}")
print(f"Size: {len(orig)} -> {len(src)}")
