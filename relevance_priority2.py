"""Inject Yandex relevance prioritization before group retry loop."""
import sys
from pathlib import Path

TARGET = Path("/root/music-bot/bot/handlers/search.py")
src = TARGET.read_text()
orig = src

OLD = '''        # Build ordered play queue: best first, then remaining candidates (not just top-4 alts)
        _play_queue = [best] + [r for r in candidates if r.get("video_id") != best.get("video_id")]

        # Try candidates in order; skip permanently-failed ones; fall back to next on error
        from bot.services.downloader import _is_permanently_failed as _pf_check
        _played = False
        for _pi, _play_cand in enumerate(_play_queue[:5]):'''

NEW = '''        # Build ordered play queue: best first, then remaining candidates (not just top-4 alts)
        _play_queue = [best] + [r for r in candidates if r.get("video_id") != best.get("video_id")]

        # ── Pre-flight: fetch fresh Yandex matches and put relevant ones first ───
        # Yandex downloads reliably, while YouTube/Spotify often hit "content unavailable".
        try:
            import re as _re_rel
            _q_words = [w.lower() for w in _re_rel.findall(r"\\w{3,}", provider_query or "")]
            _yandex_fresh = await search_yandex(provider_query, limit=5) or []
            _relevant_ym: list[dict] = []
            for _yt in _yandex_fresh:
                if not _yt.get("ym_track_id"):
                    continue
                _hay = (str(_yt.get("title", "")) + " " + str(_yt.get("uploader", ""))).lower()
                if _q_words and any(w in _hay for w in _q_words):
                    _relevant_ym.append(_yt)
            if _relevant_ym:
                _existing_vids = {c.get("video_id") for c in _play_queue}
                _new_ym = [t for t in _relevant_ym if t.get("video_id") not in _existing_vids]
                if _new_ym:
                    logger.info("Group: prioritizing %d relevant Yandex tracks (%s)",
                                len(_new_ym),
                                ", ".join(f"{t.get('uploader','')[:20]}-{t.get('title','')[:20]}"
                                          for t in _new_ym[:3]))
                    _play_queue = _new_ym + _play_queue
        except Exception as _rel_err:
            logger.debug("Group: Yandex prioritization failed: %s", _rel_err)

        # Try candidates in order; skip permanently-failed ones; fall back to next on error
        from bot.services.downloader import _is_permanently_failed as _pf_check
        _played = False
        for _pi, _play_cand in enumerate(_play_queue[:8]):'''

if NEW in src:
    print("Already applied")
    sys.exit(0)
if OLD not in src:
    print("FATAL: anchor not found")
    sys.exit(1)

src = src.replace(OLD, NEW, 1)
import ast
ast.parse(src)

bak = TARGET.with_suffix(".py.bak8")
bak.write_text(orig)
TARGET.write_text(src)
print("+ Yandex relevance prioritization + retry expanded 5→8")
print(f"Patched: {TARGET}")
