"""Add Yandex/VK fallback to cb_wrong_track_pick (was YouTube-only)."""
import sys
from pathlib import Path

TARGET = Path("/root/music-bot/bot/handlers/search.py")
src = TARGET.read_text()
orig = src

# Replace the YouTube-only fresh-search block with a multi-source one
OLD = '''    # Last-resort: fresh YouTube search
    if sent_track is None and fallback_query:
        try:
            logger.info("WrongTrackPick fallback: fresh YouTube search '%s'",
                        fallback_query[:80])
            yt_results = await search_tracks(fallback_query, max_results=3, source="youtube")
            for yt_cand in yt_results:
                yt_vid = yt_cand.get("video_id", "")
                if yt_vid in seen_vids:
                    continue
                if yt_vid and _pf_check(yt_vid):
                    continue
                logger.info("WrongTrackPick fallback try: yt_vid=%s", yt_vid)
                mp3_path, err = await _wtp_try_download(yt_cand, bitrate)
                if mp3_path and mp3_path.exists():
                    sent_track = yt_cand
                    sent_path = mp3_path
                    break
                final_err = err
                if mp3_path:
                    cleanup_file(mp3_path)
        except Exception as e:
            logger.debug("WrongTrackPick fresh-search failed: %s", e)'''

NEW = '''    # Last-resort: fresh search across Yandex → VK → YouTube
    if sent_track is None and fallback_query:
        logger.info("WrongTrackPick fallback: fresh multi-source search '%s'",
                    fallback_query[:80])
        _fresh_cands: list[dict] = []
        try:
            _ym = await search_yandex(fallback_query, limit=3)
            _fresh_cands.extend([r for r in (_ym or []) if r.get("ym_track_id")])
        except Exception as _ye:
            logger.debug("WTP fresh Yandex failed: %s", _ye)
        try:
            _vk = await search_vk(fallback_query, limit=3)
            _fresh_cands.extend([r for r in (_vk or []) if r.get("vk_url")])
        except Exception as _ve:
            logger.debug("WTP fresh VK failed: %s", _ve)
        try:
            _yt = await search_tracks(fallback_query, max_results=4, source="youtube")
            _fresh_cands.extend(_yt or [])
        except Exception as _ye2:
            logger.debug("WTP fresh YouTube failed: %s", _ye2)

        for _fi, _fc in enumerate(_fresh_cands[:8]):
            _fvid = _fc.get("video_id", "")
            if _fvid in seen_vids:
                continue
            if _fvid and _pf_check(_fvid):
                continue
            seen_vids.add(_fvid)
            logger.info("WrongTrackPick fallback try #%d: src=%s vid=%s",
                        _fi, _fc.get("source"), _fvid)
            mp3_path, err = await _wtp_try_download(_fc, bitrate)
            if mp3_path and mp3_path.exists():
                sent_track = _fc
                sent_path = mp3_path
                break
            final_err = err
            if mp3_path:
                cleanup_file(mp3_path)'''

if NEW in src:
    print("Already applied")
    sys.exit(0)
if OLD not in src:
    print("FATAL: anchor not found")
    sys.exit(1)

src = src.replace(OLD, NEW, 1)
import ast
ast.parse(src)

bak = TARGET.with_suffix(".py.bak7")
bak.write_text(orig)
TARGET.write_text(src)
print(f"+ WrongTrackPick: added Yandex/VK fallback to fresh-search")
print(f"Patched: {TARGET}")
