"""
Apply targeted patches to the LIVE server's search.py.
Run on server: python3 /tmp/server_patches.py
"""
import re
import sys
from pathlib import Path

TARGET = Path("/root/music-bot/bot/handlers/search.py")
src = TARGET.read_text()
orig = src

applied = []
skipped = []


def replace(name: str, old: str, new: str, required: bool = True) -> None:
    global src
    if new in src and old not in src:
        skipped.append(f"{name} (already applied)")
        return
    if old in src:
        src = src.replace(old, new, 1)
        applied.append(name)
        return
    if required:
        print(f"FATAL: anchor not found for '{name}'")
        sys.exit(1)
    skipped.append(f"{name} (anchor missing — skip)")


# ──────────────────────────────────────────────────────────────────────────
# Fix 1: Cyrillic-aware group trust — if query has ANY cyrillic, use cyrillic table
# Replace the "if _q_script == 'cyrillic'" check with has-cyrillic check
OLD_TRUST = """        _q_script = detect_script(provider_query) if provider_query else "mixed"
        if _q_script == "cyrillic":
            _src_trust = {"yandex": 0, "youtube": 1, "channel": 0, "vk": 2, "spotify": 3, "soundcloud": 4}
        else:
            _src_trust = {"youtube": 0, "spotify": 1, "yandex": 2, "channel": 0, "vk": 3, "soundcloud": 4}"""

NEW_TRUST = """        _q_script = detect_script(provider_query) if provider_query else "mixed"
        # Has-cyrillic check: even "mixed" scripts with any Cyrillic chars should prefer Yandex
        import re as _re_cyr
        _has_any_cyr = bool(provider_query and _re_cyr.search(r'[Ѐ-ӿ]', provider_query))
        if _q_script == "cyrillic" or _has_any_cyr:
            _src_trust = {"yandex": 0, "youtube": 1, "channel": 0, "vk": 2, "spotify": 3, "soundcloud": 4}
        else:
            _src_trust = {"youtube": 0, "spotify": 1, "yandex": 2, "channel": 0, "vk": 3, "soundcloud": 4}"""

replace("Cyrillic-aware group trust", OLD_TRUST, NEW_TRUST)


# ──────────────────────────────────────────────────────────────────────────
# Fix 2: DM download — add Yandex path logging
OLD_DM = """        try:
            if track_info.get("source") == "yandex" and track_info.get("ym_track_id"):
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

NEW_DM = """        try:
            if track_info.get("source") == "yandex" and track_info.get("ym_track_id"):
                logger.info("DM download: src=yandex ym_track_id=%s vid=%s",
                            track_info.get("ym_track_id"), video_id)
                mp3_path = settings.DOWNLOAD_DIR / f"{video_id}_{_dl_id}.mp3"
                await download_yandex(track_info["ym_track_id"], mp3_path, bitrate, token=track_info.get("_ym_token"))
            elif track_info.get("source") == "vk" and track_info.get("vk_url"):
                mp3_path = settings.DOWNLOAD_DIR / f"{video_id}_{_dl_id}.mp3"
                await download_vk(track_info["vk_url"], mp3_path)
            elif track_info.get("source") == "spotify":
                mp3_path = await _download_spotify_track(track_info, bitrate)
            else:
                if track_info.get("source") == "yandex":
                    logger.warning("DM download: src=yandex but ym_track_id MISSING! vid=%s",
                                   video_id)
                dl_vid = video_id
                if not _is_valid_yt_id(video_id):
                    dl_vid = await _resolve_yt_video_id(track_info)
                    if not dl_vid:
                        await status.edit_text(t(lang, "error_download"))
                        return
                mp3_path = await download_track(dl_vid, bitrate, progress_cb=progress_cb, dl_id=_dl_id)"""

replace("DM Yandex path logging", OLD_DM, NEW_DM, required=False)


# ──────────────────────────────────────────────────────────────────────────
# Fix 3: DM fallback — don't fallback to YouTube if error is already from YouTube
OLD_FB = """        except Exception as e:
            err_msg = str(e)
            logger.error("Download error for %s: %s", video_id, err_msg)
            # C-07: Auto-retry with a different source
            failed_source = track_info.get("source", "youtube")
            retry_query = f"{track_info.get('uploader', '')} {track_info.get('title', '')}".strip()
            if retry_query and failed_source != "youtube":
                try:
                    await status.edit_text(f"⚠️ {failed_source} недоступен, ищу альтернативу...")"""

NEW_FB = """        except Exception as e:
            err_msg = str(e)
            logger.error("Download error for %s: %s", video_id, err_msg)
            # C-07: Auto-retry with YouTube only if the original source was not YouTube,
            # AND the original error is not already a YouTube error (avoid double-retry)
            failed_source = track_info.get("source", "youtube")
            retry_query = f"{track_info.get('uploader', '')} {track_info.get('title', '')}".strip()
            _already_yt_err = "youtube" in err_msg.lower() or "ytdl" in err_msg.lower()
            if retry_query and failed_source != "youtube" and not _already_yt_err:
                try:
                    await status.edit_text(t(lang, "searching") + "...")"""

replace("DM YouTube fallback guard", OLD_FB, NEW_FB, required=False)


# ──────────────────────────────────────────────────────────────────────────
# Fix 4: change delay=10 to delay=30 in _delayed_delete defaults and call
src = src.replace(
    "async def _delayed_delete(message, session_id: str, delay: int = 10)",
    "async def _delayed_delete(message, session_id: str, delay: int = 30)",
    1,
)
src = src.replace(
    "asyncio.create_task(_delayed_delete(callback.message, session_id, 10))",
    "asyncio.create_task(_delayed_delete(callback.message, session_id, 30))",
    1,
)
applied.append("delay 10s → 30s")


# ──────────────────────────────────────────────────────────────────────────
# Fix 5: cb_wrong_track_pick → auto-retry through all alts + fresh YouTube search
OLD_CB = """@router.callback_query(WrongTrackPickCb.filter())
async def cb_wrong_track_pick(callback: CallbackQuery, callback_data: WrongTrackPickCb) -> None:
    user = await get_or_create_user(callback.from_user)
    lang = user.language
    alts = await cache.get_search(callback_data.sid)
    if not alts or callback_data.i >= len(alts):
        await callback.answer("Трек больше недоступен", show_alert=True)
        return
    track = alts[callback_data.i]
    await callback.answer(f"⬇ {track.get('title','')[:40]}")

    chat_id = callback.message.chat.id
    orig_msg_id = callback.message.message_id

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    status = await callback.bot.send_message(chat_id, t(lang, "downloading"))

    default_br = int(await _get_bot_setting("default_bitrate", "192"))
    bitrate = int(user.quality) if user.quality in ("128", "192", "320") else default_br
    video_id = track.get("video_id", "")
    mp3_path = None

    try:
        await callback.bot.send_chat_action(chat_id, ChatAction.UPLOAD_DOCUMENT)
        logger.info("WrongTrackPick: src=%s vid=%s title=%s",
                    track.get("source"), video_id, track.get("title"))

        _dl_id = uuid.uuid4().hex[:8]

        if track.get("source") == "yandex" and track.get("ym_track_id"):
            mp3_path = settings.DOWNLOAD_DIR / f"{video_id}_{_dl_id}.mp3"
            await download_yandex(track["ym_track_id"], mp3_path, bitrate,
                                  token=track.get("_ym_token"))

        elif track.get("source") == "vk" and track.get("vk_url"):
            mp3_path = settings.DOWNLOAD_DIR / f"{video_id}_{_dl_id}.mp3"
            await download_vk(track["vk_url"], mp3_path)

        else:
            dl_vid = video_id if _is_valid_yt_id(video_id) else None
            if not dl_vid:
                dl_vid = await _resolve_yt_video_id(track)
            if not dl_vid:
                await status.edit_text(t(lang, "error_download"))
                return
            mp3_path = await download_track(dl_vid, bitrate, dl_id=_dl_id)

        if not mp3_path or not mp3_path.exists():
            raise FileNotFoundError(f"MP3 not found: {video_id}")

        _af = _is_ad_free(user)
        sent = await callback.bot.send_audio(
            chat_id=chat_id,
            audio=FSInputFile(mp3_path),
            title=track.get("title", ""),
            performer=track.get("uploader", ""),
            duration=int(track["duration"]) if track.get("duration") else None,
            caption=_track_caption(lang, track, bitrate, ad_free=_af),
        )
        await cache.set_file_id(video_id, sent.audio.file_id, bitrate)
        await _post_download(user.id, track, sent.audio.file_id, bitrate)

        for mid in [status.message_id, orig_msg_id]:
            try:
                await callback.bot.delete_message(chat_id, mid)
            except Exception:
                pass

    except Exception as e:
        logger.error("WrongTrackPick failed src=%s vid=%s: %s",
                     track.get("source"), video_id, e, exc_info=True)
        try:
            await status.edit_text(t(lang, _classify_download_error(str(e))))
        except Exception:
            pass
    finally:
        if mp3_path:
            cleanup_file(mp3_path)"""

NEW_CB = '''async def _wtp_try_download(track: dict, bitrate: int):
    """Try to download a single track. Returns (mp3_path, error_message)."""
    video_id = track.get("video_id", "")
    _dl_id = uuid.uuid4().hex[:8]
    try:
        if track.get("source") == "yandex" and track.get("ym_track_id"):
            logger.info("WTP-Try: src=yandex ym_id=%s vid=%s",
                        track.get("ym_track_id"), video_id)
            mp3_path = settings.DOWNLOAD_DIR / f"{video_id}_{_dl_id}.mp3"
            await download_yandex(track["ym_track_id"], mp3_path, bitrate,
                                  token=track.get("_ym_token"))
            return mp3_path, ""
        elif track.get("source") == "vk" and track.get("vk_url"):
            logger.info("WTP-Try: src=vk vid=%s", video_id)
            mp3_path = settings.DOWNLOAD_DIR / f"{video_id}_{_dl_id}.mp3"
            await download_vk(track["vk_url"], mp3_path)
            return mp3_path, ""
        elif track.get("source") == "spotify":
            logger.info("WTP-Try: src=spotify vid=%s", video_id)
            mp3_path = await _download_spotify_track(track, bitrate)
            return mp3_path, ""
        else:
            dl_vid = video_id if _is_valid_yt_id(video_id) else None
            if not dl_vid:
                dl_vid = await _resolve_yt_video_id(track)
            if not dl_vid:
                return None, "no YouTube ID resolved"
            logger.info("WTP-Try: src=%s yt_vid=%s", track.get("source", "yt"), dl_vid)
            mp3_path = await download_track(dl_vid, bitrate, dl_id=_dl_id)
            return mp3_path, ""
    except Exception as e:
        return None, str(e)


@router.callback_query(WrongTrackPickCb.filter())
async def cb_wrong_track_pick(callback: CallbackQuery, callback_data: WrongTrackPickCb) -> None:
    """Pick an alternative — auto-retries through ALL alts + fresh YouTube search if all fail."""
    user = await get_or_create_user(callback.from_user)
    lang = user.language
    alts = await cache.get_search(callback_data.sid)
    if not alts or callback_data.i >= len(alts):
        await callback.answer("Трек больше недоступен", show_alert=True)
        return
    primary = alts[callback_data.i]
    await callback.answer(f"⬇ {primary.get('title','')[:40]}")

    chat_id = callback.message.chat.id
    orig_msg_id = callback.message.message_id
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    status = await callback.bot.send_message(chat_id, t(lang, "downloading"))
    default_br = int(await _get_bot_setting("default_bitrate", "192"))
    bitrate = int(user.quality) if user.quality in ("128", "192", "320") else default_br

    # Build candidate queue: primary first, then other alts
    seen_vids = {primary.get("video_id", "")}
    queue = [primary]
    for alt in alts:
        vid = alt.get("video_id", "")
        if vid and vid not in seen_vids:
            queue.append(alt)
            seen_vids.add(vid)
    fallback_query = f"{primary.get('uploader', '')} {primary.get('title', '')}".strip()

    from bot.services.downloader import _is_permanently_failed as _pf_check
    await callback.bot.send_chat_action(chat_id, ChatAction.UPLOAD_DOCUMENT)

    sent_track = None
    sent_path = None
    final_err = ""

    # Try each candidate in turn, skipping permanently-failed ones
    for idx, track in enumerate(queue[:5]):
        vid = track.get("video_id", "")
        if vid and _pf_check(vid):
            logger.info("WrongTrackPick: skipping perm-failed #%d vid=%s", idx, vid)
            continue
        logger.info("WrongTrackPick try #%d: src=%s vid=%s title=%s",
                    idx, track.get("source"), vid, track.get("title"))
        mp3_path, err = await _wtp_try_download(track, bitrate)
        if mp3_path and mp3_path.exists():
            sent_track = track
            sent_path = mp3_path
            break
        final_err = err
        logger.warning("WrongTrackPick try #%d failed src=%s vid=%s: %s",
                       idx, track.get("source"), vid, err)
        if mp3_path:
            cleanup_file(mp3_path)

    # Last-resort: fresh YouTube search
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
            logger.debug("WrongTrackPick fresh-search failed: %s", e)

    if sent_track is None or sent_path is None:
        logger.error("WrongTrackPick: ALL %d candidates failed. last_err=%s",
                     len(queue), final_err)
        try:
            await status.edit_text(t(lang, _classify_download_error(final_err)))
        except Exception:
            pass
        return

    try:
        _af = _is_ad_free(user)
        sent = await callback.bot.send_audio(
            chat_id=chat_id,
            audio=FSInputFile(sent_path),
            title=sent_track.get("title", ""),
            performer=sent_track.get("uploader", ""),
            duration=int(sent_track["duration"]) if sent_track.get("duration") else None,
            caption=_track_caption(lang, sent_track, bitrate, ad_free=_af),
        )
        await cache.set_file_id(sent_track.get("video_id", ""), sent.audio.file_id, bitrate)
        await _post_download(user.id, sent_track, sent.audio.file_id, bitrate)
        for mid in [status.message_id, orig_msg_id]:
            try:
                await callback.bot.delete_message(chat_id, mid)
            except Exception:
                pass
    except Exception as e:
        logger.error("WrongTrackPick: send_audio failed: %s", e, exc_info=True)
        try:
            await status.edit_text(t(lang, "error_download"))
        except Exception:
            pass
    finally:
        if sent_path:
            cleanup_file(sent_path)'''

replace("cb_wrong_track_pick → auto-retry", OLD_CB, NEW_CB)


# ──────────────────────────────────────────────────────────────────────────
# Verify syntax
import ast
try:
    ast.parse(src)
except SyntaxError as e:
    print(f"FATAL: syntax error at line {e.lineno}: {e.msg}")
    sys.exit(1)

# Backup & write
bak = TARGET.with_suffix(".py.bak")
bak.write_text(orig)
TARGET.write_text(src)

print(f"Backup: {bak}")
print(f"Updated: {TARGET}")
print(f"Original size: {len(orig)} chars")
print(f"New size:      {len(src)} chars")
print()
print("Applied:")
for a in applied:
    print(f"  + {a}")
print("Skipped:")
for s in skipped:
    print(f"  - {s}")
print()
print("Restart bot: docker compose restart bot")
