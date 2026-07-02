"""
Targeted patch script — applies new fixes to server's search.py.
Run this on the server: python3 /tmp/apply_fixes.py
"""
import re
import sys
from pathlib import Path

TARGET = Path("/root/music-bot/bot/handlers/search.py")

with open(TARGET) as f:
    src = f.read()

fixes_applied = []
fixes_skipped = []


def apply(name: str, old: str, new: str, required: bool = True):
    global src
    if old in src:
        src = src.replace(old, new, 1)
        fixes_applied.append(name)
    elif new in src:
        fixes_skipped.append(f"{name} (already applied)")
    elif required:
        print(f"ERROR: Could not find anchor for fix '{name}'")
        sys.exit(1)
    else:
        fixes_skipped.append(f"{name} (anchor not found, skipping)")


# ── Fix 1: Cyrillic-aware group source ranking ─────────────────────────────
# Check which version of the group dispatch is present
if "_q_has_cyr" in src:
    fixes_skipped.append("Cyrillic group ranking (already applied)")
elif "is_group:" in src and "_play_queue" in src:
    # New-style with retry loop — just need to add Cyrillic ranking
    # Replace the simple 'best = results[0]' fallback with cyrillic-aware
    OLD_BEST = """        # Retry loop: try best first, then up to 4 other candidates
        from bot.services.downloader import _is_permanently_failed as _pf_check"""
    NEW_BEST = """        # Cyrillic-aware source selection when no cached track found
        if best is None:
            import re as _re_grp
            from bot.services.search_engine import _SOURCE_RANK as _SRC_RANK_MIX, _SOURCE_RANK_CYR
            _q_has_cyr = bool(_re_grp.search(r'[а-яёА-ЯЁ]', provider_query))
            if _q_has_cyr:
                _grp_rank = _SOURCE_RANK_CYR
                _grp_candidates = sorted(
                    results[:5],
                    key=lambda r: _grp_rank.get(r.get("source", ""), 0),
                    reverse=True,
                )
                best = _grp_candidates[0]
                import logging as _log_grp
                _log_grp.getLogger(__name__).info(
                    "Group: Cyrillic query -> chose src=%s vid=%s title=%s",
                    best.get("source"), best.get("video_id"), best.get("title"),
                )
            else:
                best = results[0]

        # Retry loop: try best first, then up to 4 other candidates
        from bot.services.downloader import _is_permanently_failed as _pf_check"""
    apply("Cyrillic group ranking (new-style dispatch)", OLD_BEST, NEW_BEST)
elif "is_group:" in src:
    # Old-style without retry loop — more complex
    fixes_skipped.append("Cyrillic group ranking: old-style dispatch, needs full rewrite")

# ── Fix 2: DM logging for Yandex download path ─────────────────────────────
DM_YANDEX_OLD = """            if track_info.get("source") == "yandex" and track_info.get("ym_track_id"):
                mp3_path = settings.DOWNLOAD_DIR / f"{video_id}_{_dl_id}.mp3"
                await download_yandex(track_info["ym_track_id"], mp3_path, bitrate, token=track_info.get("_ym_token"))
            elif track_info.get("source") == "vk" and track_info.get("vk_url"):
                mp3_path = settings.DOWNLOAD_DIR / f"{video_id}_{_dl_id}.mp3"
                await download_vk(track_info["vk_url"], mp3_path)
            elif track_info.get("source") == "spotify":
                mp3_path = await _download_spotify_track(track_info, bitrate)
            else:
                dl_vid = video_id
                if not _is_valid_yt_id(video_id):
                    dl_vid = await _resolve_yt_video_id(track_info)
                    if not dl_vid:
                        await status.edit_text(t(lang, "error_download"))
                        return
                mp3_path = await download_track(dl_vid, bitrate, progress_cb=progress_cb, dl_id=_dl_id)"""

DM_YANDEX_NEW = """            if track_info.get("source") == "yandex" and track_info.get("ym_track_id"):
                logger.info(
                    "DM download: src=yandex ym_track_id=%s vid=%s",
                    track_info.get("ym_track_id"), video_id,
                )
                mp3_path = settings.DOWNLOAD_DIR / f"{video_id}_{_dl_id}.mp3"
                await download_yandex(track_info["ym_track_id"], mp3_path, bitrate, token=track_info.get("_ym_token"))
            elif track_info.get("source") == "vk" and track_info.get("vk_url"):
                mp3_path = settings.DOWNLOAD_DIR / f"{video_id}_{_dl_id}.mp3"
                await download_vk(track_info["vk_url"], mp3_path)
            elif track_info.get("source") == "spotify":
                mp3_path = await _download_spotify_track(track_info, bitrate)
            else:
                if track_info.get("source") == "yandex":
                    logger.warning(
                        "DM download: src=yandex but ym_track_id missing! vid=%s keys=%s",
                        video_id, list(track_info.keys()),
                    )
                dl_vid = video_id
                if not _is_valid_yt_id(video_id):
                    dl_vid = await _resolve_yt_video_id(track_info)
                    if not dl_vid:
                        await status.edit_text(t(lang, "error_download"))
                        return
                mp3_path = await download_track(dl_vid, bitrate, progress_cb=progress_cb, dl_id=_dl_id)"""

apply("DM Yandex path logging", DM_YANDEX_OLD, DM_YANDEX_NEW)

# ── Fix 3: DM fallback guard (don't retry YouTube if already on YouTube path) ──
DM_FALLBACK_OLD = """            if retry_query and failed_source != "youtube":
                try:
                    await status.edit_text(f"⚠️ {failed_source} недоступен, ищу альтернативу...")
                    alt_results = await search_tracks(retry_query, max_results=1, source="youtube")"""

DM_FALLBACK_NEW = """            _already_youtube_err = "youtube" in err_msg.lower() or "ytdl" in err_msg.lower()
            if retry_query and failed_source != "youtube" and not _already_youtube_err:
                try:
                    await status.edit_text(t(lang, "searching") + "...")
                    alt_results = await search_tracks(retry_query, max_results=1, source="youtube")"""

apply("DM fallback YouTube guard", DM_FALLBACK_OLD, DM_FALLBACK_NEW, required=False)

# ── Verify and write ───────────────────────────────────────────────────────
import ast
try:
    ast.parse(src)
    print("Syntax check: OK")
except SyntaxError as e:
    print(f"SYNTAX ERROR at line {e.lineno}: {e.msg}")
    sys.exit(1)

# Backup original
bak = TARGET.with_suffix(".py.bak")
bak.write_text(TARGET.read_text())
print(f"Backup: {bak}")

TARGET.write_text(src)
print(f"Written: {TARGET}")

print("\nFixes applied:")
for f in fixes_applied:
    print(f"  + {f}")
print("Fixes skipped:")
for f in fixes_skipped:
    print(f"  - {f}")
print("\nDone. Restart with: docker compose restart bot")
