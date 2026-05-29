"""Add fresh Yandex/VK search as last-resort fallback in group auto-play."""
import sys
from pathlib import Path

TARGET = Path("/root/music-bot/bot/handlers/search.py")
src = TARGET.read_text()
orig = src

# Locate the group retry loop's "all 5 failed" branch
OLD = '''        if not _played:
            try:
                await status.edit_text(t(lang, "error_download"))
            except Exception:
                pass
        return'''

NEW = '''        # Last-resort: if ALL 5 candidates failed, try a FRESH search across Yandex/VK
        if not _played:
            _retry_q = provider_query.strip() if provider_query else ""
            if _retry_q:
                logger.info("Group: all 5 candidates failed, trying fresh Yandex/VK search for '%s'",
                            _retry_q[:80])
                _fresh_cands: list[dict] = []
                try:
                    _ym_fresh = await search_yandex(_retry_q, limit=3)
                    _fresh_cands.extend([r for r in (_ym_fresh or []) if r.get("ym_track_id")])
                except Exception as _y_err:
                    logger.debug("Group fresh Yandex search failed: %s", _y_err)
                try:
                    _vk_fresh = await search_vk(_retry_q, limit=3)
                    _fresh_cands.extend([r for r in (_vk_fresh or []) if r.get("vk_url")])
                except Exception as _v_err:
                    logger.debug("Group fresh VK search failed: %s", _v_err)
                # Try each fresh candidate
                _seen_fresh_vids = set()
                for _fi, _fcand in enumerate(_fresh_cands[:4]):
                    _fvid = _fcand.get("video_id", "")
                    if not _fvid or _fvid in _seen_fresh_vids:
                        continue
                    _seen_fresh_vids.add(_fvid)
                    logger.info("Group fresh-fallback try #%d: src=%s vid=%s title=%s",
                                _fi, _fcand.get("source"), _fvid, _fcand.get("title"))
                    try:
                        await _group_auto_play(message, status, user, _fcand, raise_on_error=True)
                        _played = True
                        break
                    except Exception as _fp_err:
                        logger.warning("Group fresh-fallback #%d failed (%s): %s",
                                       _fi, _fvid, _fp_err)
                        continue
        if not _played:
            try:
                await status.edit_text(t(lang, "error_download"))
            except Exception:
                pass
        return'''

if NEW in src:
    print("Already applied")
    sys.exit(0)
if OLD not in src:
    print("FATAL: anchor not found")
    sys.exit(1)

src = src.replace(OLD, NEW, 1)

# Verify
import ast
ast.parse(src)

bak = TARGET.with_suffix(".py.bak6")
bak.write_text(orig)
TARGET.write_text(src)

print(f"+ Group last-resort fresh Yandex/VK search added")
print(f"Patched: {TARGET}")
print(f"Backup:  {bak}")
print(f"Size: {len(orig)} -> {len(src)}")
