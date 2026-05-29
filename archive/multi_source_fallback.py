"""Add multi-source fallback (Yandex → VK → SC) when YouTube is fully blocked."""
import sys
from pathlib import Path

TARGET = Path("/root/music-bot/bot/handlers/search.py")
src = TARGET.read_text()
orig = src

# Improve pre-flight check: try Yandex FIRST, then VK, then YT
OLD_PREFLIGHT = '''    # Pre-flight: if selected track is permanently failed, swap for a fresh YouTube result
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
        pass'''

NEW_PREFLIGHT = '''    # Pre-flight: if selected track is permanently failed, try alternative sources
    try:
        from bot.services.downloader import _is_permanently_failed as _pf
        if video_id and _pf(video_id):
            logger.info("Track %s is perm-failed — searching alternative sources", video_id)
            _retry_q = f"{track_info.get('uploader', '')} {track_info.get('title', '')}".strip()
            if _retry_q:
                _swapped = False
                # Try Yandex first (most reliable for Russian/Mixed content)
                try:
                    _ym = await search_yandex(_retry_q, limit=3)
                    for _cand in (_ym or []):
                        if _cand.get("ym_track_id"):
                            logger.info("Pre-flight: swapped perm-failed %s → ym_%s (Yandex)",
                                        video_id, _cand.get("ym_track_id"))
                            track_info = _cand
                            video_id = _cand.get("video_id", "")
                            _share_q = f"{track_info.get('uploader', '')} - {track_info.get('title', '')}"
                            _swapped = True
                            break
                except Exception as _y_err:
                    logger.debug("Pre-flight Yandex search failed: %s", _y_err)
                # Try VK if Yandex didn't return anything
                if not _swapped:
                    try:
                        _vk = await search_vk(_retry_q, limit=3)
                        for _cand in (_vk or []):
                            if _cand.get("vk_url"):
                                logger.info("Pre-flight: swapped perm-failed %s → vk %s",
                                            video_id, _cand.get("video_id"))
                                track_info = _cand
                                video_id = _cand.get("video_id", "")
                                _share_q = f"{track_info.get('uploader', '')} - {track_info.get('title', '')}"
                                _swapped = True
                                break
                    except Exception as _v_err:
                        logger.debug("Pre-flight VK search failed: %s", _v_err)
                # Last: YouTube (filter out perm-failed)
                if not _swapped:
                    try:
                        _alt_tracks = await search_tracks(_retry_q, max_results=8, source="youtube")
                        for _cand in _alt_tracks:
                            _cvid = _cand.get("video_id", "")
                            if _cvid and not _pf(_cvid):
                                logger.info("Pre-flight: swapped perm-failed %s → %s (YouTube)",
                                            video_id, _cvid)
                                track_info = _cand
                                video_id = _cvid
                                _share_q = f"{track_info.get('uploader', '')} - {track_info.get('title', '')}"
                                break
                    except Exception as _swap_err:
                        logger.debug("Pre-flight YT swap failed: %s", _swap_err)
    except Exception:
        pass'''

if NEW_PREFLIGHT in src:
    print("Already applied — preflight")
elif OLD_PREFLIGHT not in src:
    print("WARN: preflight anchor not found")
else:
    src = src.replace(OLD_PREFLIGHT, NEW_PREFLIGHT, 1)
    print("+ Multi-source preflight (Yandex → VK → YT)")


# Also: when the DM download fails, try Yandex/VK fallback first, then YT
OLD_RETRY_BLOCK = '''            # Auto-retry: search for OTHER YouTube candidates (not the failed one) and try them
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

NEW_RETRY_BLOCK = '''            # Auto-retry: try Yandex/VK first, then OTHER YouTube candidates
            failed_source = track_info.get("source", "youtube")
            retry_query = f"{track_info.get('uploader', '')} {track_info.get('title', '')}".strip()
            if retry_query:
                try:
                    from bot.services.downloader import _is_permanently_failed as _pf_retry
                    await status.edit_text(t(lang, "searching") + "...")
                    alt_results = []
                    # Strategy 1: Yandex (skip if already tried)
                    if failed_source != "yandex":
                        try:
                            _y_alts = await search_yandex(retry_query, limit=2)
                            alt_results.extend([r for r in (_y_alts or []) if r.get("ym_track_id")])
                        except Exception:
                            pass
                    # Strategy 2: VK (skip if already tried)
                    if failed_source != "vk":
                        try:
                            _vk_alts = await search_vk(retry_query, limit=2)
                            alt_results.extend([r for r in (_vk_alts or []) if r.get("vk_url")])
                        except Exception:
                            pass
                    # Strategy 3: YouTube candidates (filter out perm-failed and original)
                    try:
                        _yt_alts = await search_tracks(retry_query, max_results=5, source="youtube")
                        alt_results.extend([r for r in (_yt_alts or [])
                                            if r.get("video_id") != video_id
                                            and not _pf_retry(r.get("video_id", ""))])
                    except Exception:
                        pass'''

if NEW_RETRY_BLOCK in src:
    print("Already applied — retry block")
elif OLD_RETRY_BLOCK not in src:
    print("WARN: retry block anchor not found — diff probably already partially applied")
else:
    src = src.replace(OLD_RETRY_BLOCK, NEW_RETRY_BLOCK, 1)
    print("+ Multi-source DM auto-retry (Yandex+VK+YT)")


# Now we also need to fix the retry download call — it currently uses download_track
# (YouTube only). Change it to dispatch to the right downloader by source.
OLD_RETRY_DL = '''                    if alt_results:
                        retry_id = uuid.uuid4().hex[:8]
                        retry_path = await download_track(alt_results[0]["video_id"], bitrate, dl_id=retry_id)
                        try:
                            sent = await callback.message.answer_audio(
                                audio=FSInputFile(retry_path),'''

NEW_RETRY_DL = '''                    if alt_results:
                        retry_id = uuid.uuid4().hex[:8]
                        _alt_track = alt_results[0]
                        _alt_src = _alt_track.get("source", "youtube")
                        _alt_vid = _alt_track.get("video_id", "")
                        # Dispatch to the right downloader based on source
                        if _alt_src == "yandex" and _alt_track.get("ym_track_id"):
                            retry_path = settings.DOWNLOAD_DIR / f"{_alt_vid}_{retry_id}.mp3"
                            await download_yandex(_alt_track["ym_track_id"], retry_path, bitrate,
                                                  token=_alt_track.get("_ym_token"))
                        elif _alt_src == "vk" and _alt_track.get("vk_url"):
                            retry_path = settings.DOWNLOAD_DIR / f"{_alt_vid}_{retry_id}.mp3"
                            await download_vk(_alt_track["vk_url"], retry_path)
                        else:
                            retry_path = await download_track(_alt_vid, bitrate, dl_id=retry_id)
                        logger.info("DM retry: succeeded via src=%s vid=%s", _alt_src, _alt_vid)
                        try:
                            sent = await callback.message.answer_audio(
                                audio=FSInputFile(retry_path),'''

if NEW_RETRY_DL in src:
    print("Already applied — retry download dispatch")
elif OLD_RETRY_DL not in src:
    print("WARN: retry download anchor not found")
else:
    src = src.replace(OLD_RETRY_DL, NEW_RETRY_DL, 1)
    print("+ Multi-source retry download dispatch")


# Verify and write
import ast
ast.parse(src)

bak = TARGET.with_suffix(".py.bak5")
bak.write_text(orig)
TARGET.write_text(src)
print(f"\nPatched: {TARGET}")
print(f"Backup:  {bak}")
print(f"Size: {len(orig)} -> {len(src)}")
