import asyncio
import json as _json
import logging
import secrets
import time
import uuid
from pathlib import Path

from aiogram import Router
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.config import settings
from bot.db import get_or_create_user, get_popular_titles, get_random_popular_track, increment_request_count, record_listening_event, search_local_tracks, upsert_track
from bot.i18n import t
from bot.services.cache import cache
from bot.services.downloader import cleanup_file, download_track, search_tracks, is_youtube_url, extract_youtube_video_id, resolve_youtube_url
from bot.services.spotify_provider import is_spotify_url, resolve_spotify_url, search_spotify
from bot.services.vk_provider import download_vk, search_vk
from bot.services.yandex_provider import download_yandex, search_yandex, is_yandex_music_url, resolve_yandex_url
from bot.services.metrics import cache_hits, cache_misses, requests_total
from bot.services.provider_health import record_provider_event
from bot.services.search_engine import deduplicate_results, suggest_query
from bot.services.analytics import track_event
from bot.services.share_links import create_share_link, resolve_share_link
from bot.callbacks import TrackCallback, FeedbackCallback, AddToPlCb, AddToQueueCb, LyricsCb, LyrTransCb, FavoriteCb, ShareTrackCb, SimilarCb, StoryCb
from bot.utils import fmt_duration

logger = logging.getLogger(__name__)

router = Router()

_TRACK_SHARE_TTL = 30 * 24 * 3600  # 30 days
_DOWNLOAD_LOCK_TTL = 10


def _classify_download_error(err_msg: str) -> str:
    """Return i18n key for a download error message."""
    if "Sign in to confirm your age" in err_msg:
        return "error_age_restricted"
    if "not available" in err_msg.lower() or "geo" in err_msg.lower() or "blocked" in err_msg.lower():
        return "error_geo_restricted"
    if "timed out" in err_msg.lower() or "timeout" in err_msg.lower():
        return "error_timeout"
    return "error_download"

# Group chat auto-cleanup timeout (seconds)
_GROUP_CLEANUP_SEC = 60

# Search result limits
_MAX_RESULTS_GROUP = 1      # In groups — just one track

# ── Download progress ─────────────────────────────────────────────────────

_PROGRESS_BARS = ["▏", "▎", "▍", "▌", "▋", "▊", "▉", "█"]


def _make_progress_bar(pct: int) -> str:
    """Build a compact 10-char progress bar from percentage."""
    filled = pct // 10
    return "█" * filled + "░" * (10 - filled)


def _make_progress_cb(status_msg, lang: str):
    """Create a thread-safe progress callback that throttles Telegram edits.

    Returns (callback_fn, last_edit_state_dict).
    The callback can be invoked from a worker thread — it schedules edits on the event loop.
    """
    loop = asyncio.get_event_loop()
    state = {"last_pct": -1, "last_edit": 0.0}

    def _on_progress(downloaded: int, total: int) -> None:
        pct = int(downloaded * 100 / total) if total else 0
        now = time.monotonic()
        # Only update every 20% or every 3 seconds (Telegram rate limits)
        if pct - state["last_pct"] < 20 and now - state["last_edit"] < 3:
            return
        state["last_pct"] = pct
        state["last_edit"] = now
        bar = _make_progress_bar(pct)
        mb_dl = downloaded / (1024 * 1024)
        mb_tt = total / (1024 * 1024)
        text = f"⬇ {t(lang, 'downloading')} {pct}%\n{bar}  {mb_dl:.1f} / {mb_tt:.1f} MB"
        asyncio.run_coroutine_threadsafe(_safe_edit(status_msg, text), loop)

    return _on_progress


import re as _re
_YT_ID_RE = _re.compile(r'^[A-Za-z0-9_-]{11}$')


def _is_valid_yt_id(video_id: str) -> bool:
    """Check if a string looks like a valid YouTube video ID (11 chars, base64url)."""
    return bool(_YT_ID_RE.match(video_id))


async def _resolve_yt_video_id(track_info: dict) -> str | None:
    """For non-YouTube tracks without a valid video_id, search YouTube by artist+title."""
    query = f"{track_info.get('uploader', '')} - {track_info.get('title', '')}"
    yt_results = await search_tracks(query.strip(), max_results=1, source="youtube")
    if yt_results:
        return yt_results[0]["video_id"]
    return None


async def _safe_edit(msg, text: str) -> None:
    """Edit message text, ignoring any Telegram errors."""
    try:
        await msg.edit_text(text)
    except Exception:
        logger.debug("safe_edit failed", exc_info=True)


def _download_lock_key(user_id: int, track_id: str) -> str:
    return f"download:{user_id}:{track_id}"


async def _acquire_download_lock(user_id: int, track_id: str, ttl: int = _DOWNLOAD_LOCK_TTL) -> bool:
    """Acquire a short Redis lock for a user+track download flow.

    Fail-open if Redis is unavailable to avoid blocking playback.
    """
    try:
        key = _download_lock_key(user_id, track_id)
        acquired = await cache.redis.set(key, "1", ex=ttl, nx=True)
        return bool(acquired)
    except Exception:
        return True


async def _release_download_lock(user_id: int, track_id: str) -> None:
    """Release user+track download lock (best-effort)."""
    try:
        key = _download_lock_key(user_id, track_id)
        await cache.redis.delete(key)
    except Exception:
        logger.debug("release_download_lock failed user=%s", user_id, exc_info=True)


def _smart_bitrate(source: str | None, duration: int | None, default_br: int) -> int:
    """TASK-024: Choose bitrate based on source and duration.

    - Yandex → 320 (native)
    - Duration > 300s (5 min) → 192 to save traffic
    - Otherwise use default_br
    """
    if source == "yandex":
        return 320
    if duration and duration > 300:
        return min(default_br, 192)
    return default_br


async def _get_bot_setting(key: str, default: str) -> str:
    """Read admin-set setting from Redis (same keys as admin panel)."""
    val = await cache.redis.get(f"bot:setting:{key}")
    if val:
        return val if isinstance(val, str) else val.decode()
    return default

# session_id → {chat_id, user_msg_id, status_msg_id, created_at}
_group_sessions: dict[str, dict] = {}
_group_sessions_lock = asyncio.Lock()


async def _schedule_group_cleanup(bot, session_id: str) -> None:
    """Delete search messages in group if no track selected within timeout."""
    await asyncio.sleep(_GROUP_CLEANUP_SEC)
    async with _group_sessions_lock:
        info = _group_sessions.pop(session_id, None)
    if not info:
        return
    for mid in (info.get("status_msg_id"), info.get("user_msg_id")):
        if mid:
            try:
                await bot.delete_message(info["chat_id"], mid)
            except Exception:
                logger.debug("group cleanup delete msg=%s failed", mid, exc_info=True)


async def _cleanup_group_search(bot, session_id: str, results_msg: Message) -> None:
    """After track is selected in group: delete original message + search results."""
    async with _group_sessions_lock:
        info = _group_sessions.pop(session_id, None)
    # Delete the search results message (the inline keyboard message)
    try:
        await results_msg.delete()
    except Exception:
        logger.debug("cleanup group search results delete failed", exc_info=True)
    if not info:
        return
    # Delete the original user message
    if info.get("user_msg_id"):
        try:
            await bot.delete_message(info["chat_id"], info["user_msg_id"])
        except Exception:
            logger.debug("cleanup group user msg delete failed", exc_info=True)


# TrackCallback, FeedbackCallback, AddToPlCb imported from bot.callbacks


def _track_caption(lang: str, track_info: dict, bitrate: int, *, ad_free: bool = False) -> str:
    """Build caption line: ◷ 3:42 · 192 kbps · 2019 · ◉ BLACK ROOM"""
    dur = track_info.get("duration_fmt") or "?:??"
    year = track_info.get("upload_year")
    year_str = f" · {year}" if year else ""
    base = t(lang, "track_caption", duration=dur, bitrate=bitrate, year=year_str)
    if ad_free:
        return base
    return f"{base}\n◉ BLACK ROOM"


def _is_ad_free(user) -> bool:
    """Check if user has ad-free (Premium, admin, or paid ad-free period)."""
    if user.is_premium or user.is_admin:
        return True
    from datetime import datetime, timezone as tz
    if user.ad_free_until and user.ad_free_until > datetime.now(tz.utc):
        return True
    return False


_SEARCH_LOGO = "\u25c9 <b>BLACK ROOM</b>"


def _build_results_keyboard(results: list[dict], session_id: str) -> InlineKeyboardMarkup:
    buttons = []
    for i, track in enumerate(results):
        label = f"♪ {track['uploader']} — {track['title'][:40]} ({track['duration_fmt']})"
        buttons.append(
            [InlineKeyboardButton(
                text=label,
                callback_data=TrackCallback(sid=session_id, i=i).pack(),
            )]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _do_search(message: Message, query: str) -> None:
    try:
        user = await get_or_create_user(message.from_user)
    except Exception:
        await message.answer("⚠️ Сервис временно недоступен. Попробуй снова.")
        return
    lang = user.language

    if user.is_banned:
        return

    # Admins bypass rate limits
    if message.from_user.id not in settings.ADMIN_IDS:
        allowed, cooldown = await cache.check_rate_limit(
            message.from_user.id, is_premium=user.is_premium
        )
        if not allowed:
            if cooldown > 0:
                await message.answer(t(lang, "rate_limit_cooldown", seconds=cooldown))
            else:
                await message.answer(t(lang, "rate_limit_exceeded"))
            return

    # Spotify link → resolve via Spotify API, show track directly
    if is_spotify_url(query):
        status = await message.answer(t(lang, "spotify_detected"))
        track_info = await resolve_spotify_url(query)
        if not track_info:
            await status.edit_text(t(lang, "no_results"))
            return
        await record_listening_event(
            user_id=user.id, query=query[:500], action="search", source="spotify"
        )
        requests_total.labels(source="spotify").inc()
        is_group = message.chat.type in ("group", "supergroup")
        if is_group:
            await _group_auto_play(message, status, user, track_info)
        else:
            session_id = secrets.token_urlsafe(6)
            await cache.store_search(session_id, [track_info])
            keyboard = _build_results_keyboard([track_info], session_id)
            await status.edit_text(
                f"{_SEARCH_LOGO}\n\n"
                f"▸ Spotify\n"
                f"♪ <b>{track_info['uploader']} — {track_info['title']}</b> ({track_info['duration_fmt']})",
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        return
    # Yandex Music link → fetch track directly, skip search
    elif is_yandex_music_url(query):
        status = await message.answer(t(lang, "yandex_link_detected"))
        track_info = await resolve_yandex_url(query)
        if not track_info:
            await status.edit_text(t(lang, "no_results"))
            return
        await record_listening_event(
            user_id=user.id, query=query[:500], action="search", source="yandex"
        )
        requests_total.labels(source="yandex").inc()
        is_group = message.chat.type in ("group", "supergroup")
        if is_group:
            await _group_auto_play(message, status, user, track_info)
        else:
            session_id = secrets.token_urlsafe(6)
            await cache.store_search(session_id, [track_info])
            keyboard = _build_results_keyboard([track_info], session_id)
            await status.edit_text(
                f"{_SEARCH_LOGO}\n\n"
                f"▸ Яндекс.Музыка\n"
                f"♪ <b>{track_info['uploader']} — {track_info['title']}</b> ({track_info['duration_fmt']})",
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        return
    # YouTube link → resolve metadata, download directly
    elif is_youtube_url(query):
        video_id = extract_youtube_video_id(query)
        if not video_id:
            return
        status = await message.answer(t(lang, "youtube_link_detected"))
        track_info = await resolve_youtube_url(video_id)
        if not track_info:
            await status.edit_text(t(lang, "no_results"))
            return
        await record_listening_event(
            user_id=user.id, query=query[:500], action="search", source="youtube"
        )
        requests_total.labels(source="youtube").inc()
        is_group = message.chat.type in ("group", "supergroup")
        if is_group:
            await _group_auto_play(message, status, user, track_info)
        else:
            session_id = secrets.token_urlsafe(6)
            await cache.store_search(session_id, [track_info])
            keyboard = _build_results_keyboard([track_info], session_id)
            await status.edit_text(
                f"{_SEARCH_LOGO}\n\n"
                f"▸ YouTube\n"
                f"♪ <b>{track_info['uploader']} — {track_info['title']}</b> ({track_info['duration_fmt']})",
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        return
    else:
        await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        status = await message.answer(t(lang, "searching"))

    is_group = message.chat.type in ("group", "supergroup")
    if is_group:
        max_results = _MAX_RESULTS_GROUP
    else:
        max_results = int(await _get_bot_setting("max_results", "10"))

    # STEP 1: Search local DB (TEQUILA / FULLMOON channels + cached tracks)
    local_tracks = await search_local_tracks(query, limit=max_results)
    local_results = []
    for idx, tr in enumerate(local_tracks or []):
        local_results.append({
            "video_id": tr.source_id,
            "title": tr.title or "Unknown",
            "uploader": tr.artist or "Unknown",
            "duration": tr.duration or 0,
            "duration_fmt": _fmt_duration(tr.duration) if tr.duration else "?:??",
            "source": tr.source or "channel",
            "file_id": tr.file_id,
            "_provider_pos": idx,
        })

    # STEP 2: Parallel external search — Yandex + Spotify + SoundCloud + VK + YouTube
    async def _search_source(source: str, search_fn, limit: int) -> list[dict]:
        """Search a single source with cache and 8s timeout."""
        t0 = time.monotonic()
        try:
            cached = await cache.get_query_cache(query, source)
            if cached is not None:
                return cached
            res = await asyncio.wait_for(search_fn(query, limit=limit), timeout=8)
            elapsed = time.monotonic() - t0
            record_provider_event(source, "search", elapsed, True)
            if res:
                await cache.set_query_cache(query, res, source)
                requests_total.labels(source=source).inc()
            return res or []
        except Exception as exc:
            elapsed = time.monotonic() - t0
            record_provider_event(source, "search", elapsed, False, str(exc))
            logger.debug("search source %s failed", source, exc_info=True)
            return []

    async def _search_sc(query_: str, limit: int = 5) -> list[dict]:
        return await search_tracks(query_, max_results=limit, source="soundcloud")

    async def _search_yt(query_: str, limit: int = 5) -> list[dict]:
        return await search_tracks(query_, max_results=limit, source="youtube")

    from bot.services.search_engine import detect_script, transliterate_cyr_to_lat, transliterate_lat_to_cyr

    tasks = [
        _search_source("yandex", search_yandex, max_results),
        _search_source("spotify", search_spotify, max_results),
        _search_source("soundcloud", _search_sc, max_results),
        _search_source("vk", search_vk, max_results),
        _search_source("youtube", _search_yt, max_results),
    ]
    source_results = await asyncio.gather(*tasks, return_exceptions=True)
    all_results: list[dict] = []
    for batch in source_results:
        if isinstance(batch, BaseException):
            continue
        # Stamp provider position so ranking preserves provider relevance order
        for i, track in enumerate(batch):
            track["_provider_pos"] = i
        all_results.extend(batch)

    # A-05: If few results and query is mono-language, try transliterated search
    if len(all_results) < 3:
        script = detect_script(query)
        alt_query = None
        if script == "cyrillic":
            alt_query = transliterate_cyr_to_lat(query)
        elif script == "latin":
            alt_query = transliterate_lat_to_cyr(query)
        if alt_query and alt_query != query:
            alt_tasks = [
                _search_source("youtube", lambda q, limit=5: search_tracks(alt_query, max_results=limit, source="youtube"), max_results),
                _search_source("yandex", lambda q, limit=5: search_yandex(alt_query, limit=limit), max_results),
            ]
            alt_results = await asyncio.gather(*alt_tasks, return_exceptions=True)
            for batch in alt_results:
                if isinstance(batch, BaseException):
                    continue
                all_results.extend(batch)

    # Merge local + external results, then deduplicate
    all_results = local_results + all_results

    # Deduplicate across sources (language-aware ranking)
    script = detect_script(query)
    results = deduplicate_results(all_results, lang_hint=script, query=query)[:max_results] if all_results else []

    # DMCA filter: remove blocked tracks, show appeal button if any were blocked
    blocked_count = 0
    if results:
        from bot.services.dmca_filter import filter_blocked, is_blocked
        before_count = len(results)
        # Find the first blocked track for the appeal button
        blocked_source_id = None
        for r in results:
            if is_blocked(r.get("video_id", "")):
                blocked_source_id = r.get("video_id", "")
                break
        results = filter_blocked(results)
        blocked_count = before_count - len(results)

    if not results:
        # TASK-012: "Did you mean?" suggestions
        try:
            corpus = await get_popular_titles(limit=500)
            suggestions = suggest_query(query, corpus, max_suggestions=1)
        except Exception:
            suggestions = []
        if suggestions:
            sug = suggestions[0]
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=f'🔍 "{sug}"', switch_inline_query_current_chat=sug),
            ]])
            await status.edit_text(
                f"{t(lang, 'no_results')}\n\n💡 {t(lang, 'did_you_mean')}",
                reply_markup=kb,
                parse_mode="HTML",
            )
        else:
            await status.edit_text(t(lang, "no_results"))
        return

    await record_listening_event(
        user_id=user.id, query=query[:500], action="search", source="search"
    )

    # Groups: auto-play first track — prefer cached tracks for instant delivery
    if is_group:
        best = results[0]
        # Check top-3 results: if any has file_id or redis cache, use it instead
        for candidate in results[:3]:
            if candidate.get("file_id"):
                best = candidate
                break
            fid = await cache.get_file_id(candidate.get("video_id", ""), bitrate=192)
            if fid:
                candidate["file_id"] = fid
                best = candidate
                break
        await _group_auto_play(message, status, user, best)
        return

    session_id = secrets.token_urlsafe(6)
    await cache.store_search(session_id, results)
    keyboard = _build_results_keyboard(results, session_id)
    # Collect unique sources
    _source_tags = {"soundcloud": "SoundCloud", "vk": "VK Music", "yandex": "Яндекс.Музыка", "spotify": "Spotify", "youtube": "YouTube", "channel": "Каталог"}
    sources_used = []
    for r in results:
        s = r.get("source", "youtube")
        tag = _source_tags.get(s, s)
        if tag not in sources_used:
            sources_used.append(tag)
    source_line = " · ".join(sources_used) if sources_used else "YouTube"
    await status.edit_text(
        f"{_SEARCH_LOGO}\n\n"
        f"<b>{t(lang, 'search_results')}:</b> {query}\n"
        f"▸ {source_line} · {len(results)} треков",
        reply_markup=keyboard,
        parse_mode="HTML",
    )

    # Show appeal button if any tracks were blocked
    if blocked_count > 0 and blocked_source_id:
        from bot.callbacks import AppealCb
        appeal_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text=t(lang, "dmca_appeal_btn"),
                callback_data=AppealCb(sid=blocked_source_id[:30]).pack(),
            )
        ]])
        await message.answer(
            t(lang, "dmca_blocked_notice", count=blocked_count),
            reply_markup=appeal_kb,
            parse_mode="HTML",
        )


async def _download_spotify_track(track_info: dict, bitrate: int) -> Path:
    """Download a Spotify track via Yandex Music (preferred) or YouTube fallback."""
    query = track_info.get("yt_query") or f"{track_info['uploader']} - {track_info['title']}"
    video_id = track_info["video_id"]

    # Try Yandex first — best quality
    ym_results = await search_yandex(query, limit=1)
    if ym_results and ym_results[0].get("ym_track_id"):
        _dl_id = uuid.uuid4().hex[:8]
        dest = settings.DOWNLOAD_DIR / f"{video_id}_{_dl_id}.mp3"
        await download_yandex(ym_results[0]["ym_track_id"], dest, bitrate)
        return dest

    # Fallback: search YouTube and download
    yt_results = await search_tracks(query, max_results=1, source="youtube")
    if yt_results:
        return await download_track(yt_results[0]["video_id"], bitrate, dl_id=uuid.uuid4().hex[:8])

    raise RuntimeError(f"No downloadable source found for Spotify track: {query}")


async def _group_auto_play(
    message: Message, status: Message, user, track_info: dict
) -> None:
    """In groups: download and send the first track immediately, then clean up."""
    lang = user.language
    default_br = int(await _get_bot_setting("default_bitrate", "192"))
    bitrate = int(user.quality) if user.quality in ("128", "192", "320") else _smart_bitrate(
        track_info.get("source"), track_info.get("duration"), default_br
    )
    video_id = track_info["video_id"]

    # Local file_id (channel tracks)
    _af = _is_ad_free(user)
    local_fid = track_info.get("file_id")
    if local_fid:
        caption = _track_caption(lang, track_info, bitrate, ad_free=_af)
        await message.answer_audio(
            audio=local_fid,
            title=track_info["title"],
            performer=track_info["uploader"],
            duration=int(track_info["duration"]) if track_info.get("duration") else None,
            caption=caption,
        )
        await _post_download(user.id, track_info, local_fid, bitrate)
        await _delete_msgs(message.bot, message.chat.id, [status.message_id, message.message_id])
        return

    # Redis cache → DB fallback
    file_id = await cache.get_file_id(video_id, bitrate)
    if not file_id:
        try:
            from bot.services.telegram_cache import get_file_id as _tg_get_fid
            file_id = await _tg_get_fid(video_id)
        except Exception:
            pass
    if file_id:
        caption = _track_caption(lang, track_info, bitrate, ad_free=_af)
        await message.answer_audio(
            audio=file_id,
            title=track_info["title"],
            performer=track_info["uploader"],
            duration=int(track_info["duration"]) if track_info.get("duration") else None,
            caption=caption,
        )
        await _post_download(user.id, track_info, file_id, bitrate)
        await _delete_msgs(message.bot, message.chat.id, [status.message_id, message.message_id])
        return

    # Download
    await status.edit_text(t(lang, "downloading"))
    await message.bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_DOCUMENT)
    mp3_path: Path | None = None
    try:
        _dl_id = uuid.uuid4().hex[:8]
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
            mp3_path = await download_track(dl_vid, bitrate, dl_id=_dl_id)
        file_size = mp3_path.stat().st_size
        if file_size > settings.MAX_FILE_SIZE and bitrate > 128 and track_info.get("source") not in ("vk", "yandex"):
            cleanup_file(mp3_path)
            mp3_path = None
            dl_vid = video_id if _is_valid_yt_id(video_id) else (await _resolve_yt_video_id(track_info) or video_id)
            try:
                mp3_path = await download_track(dl_vid, 128, dl_id=_dl_id)
                bitrate = 128
                file_size = mp3_path.stat().st_size
            except Exception:
                mp3_path = None
                await status.edit_text(t(lang, "error_too_large_final"))
                return
            if file_size > settings.MAX_FILE_SIZE:
                cleanup_file(mp3_path)
                mp3_path = None
                await status.edit_text(t(lang, "error_too_large_final"))
                return
        sent = await message.answer_audio(
            audio=FSInputFile(mp3_path),
            title=track_info["title"],
            performer=track_info["uploader"],
            duration=int(track_info["duration"]) if track_info.get("duration") else None,
            caption=_track_caption(lang, track_info, bitrate, ad_free=_af),
        )
        await cache.set_file_id(video_id, sent.audio.file_id, bitrate)
        await _post_download(user.id, track_info, sent.audio.file_id, bitrate)
        await _delete_msgs(message.bot, message.chat.id, [status.message_id, message.message_id])
    except Exception as e:
        err_msg = str(e)
        logger.error("Group auto-play error for %s: %s", video_id, err_msg)
        await status.edit_text(t(lang, _classify_download_error(err_msg)))
    finally:
        if mp3_path:
            cleanup_file(mp3_path)


async def _delete_msgs(bot, chat_id: int, msg_ids: list[int]) -> None:
    """Silently delete messages in a group chat."""
    for mid in msg_ids:
        if mid:
            try:
                await bot.delete_message(chat_id, mid)
            except Exception:
                logger.debug("delete_msgs mid=%s failed", mid, exc_info=True)


# fmt_duration imported from bot.utils
_fmt_duration = fmt_duration


# ── DMCA Appeal handler ───────────────────────────────────────────────────

from bot.callbacks import AppealCb


@router.callback_query(AppealCb.filter())
async def cb_dmca_appeal(callback: CallbackQuery, callback_data: AppealCb) -> None:
    """Handle DMCA appeal button click."""
    user = await get_or_create_user(callback.from_user)
    lang = user.language
    source_id = callback_data.sid

    # Find the blocked track in DB
    from bot.models.blocked_track import BlockedTrack
    from bot.models.base import async_session as _async_session
    from sqlalchemy import select as _select

    async with _async_session() as session:
        result = await session.execute(
            _select(BlockedTrack).where(BlockedTrack.source_id == source_id)
        )
        blocked = result.scalar_one_or_none()

    if not blocked:
        await callback.answer(t(lang, "dmca_appeal_not_found"), show_alert=True)
        return

    from bot.services.dmca_filter import create_appeal
    appeal_id = await create_appeal(
        user_id=user.id,
        blocked_track_id=blocked.id,
        reason=f"User appeal for {source_id}",
    )
    if appeal_id:
        await callback.answer()
        await callback.message.edit_text(
            t(lang, "dmca_appeal_sent", appeal_id=appeal_id),
            parse_mode="HTML",
        )
    else:
        await callback.answer(t(lang, "dmca_appeal_error"), show_alert=True)


@router.message(Command("search"))
async def cmd_search(message: Message) -> None:
    query = message.text.removeprefix("/search").strip()[:500]
    if not query:
        user = await get_or_create_user(message.from_user)
        await message.answer(t(user.language, "search_prompt"))
        return
    await _do_search(message, query)


@router.message(lambda m: m.text and not m.text.startswith("/"))
async def handle_text(message: Message) -> None:
    text = message.text.strip()[:500]
    lower = text.lower()

    # "что играет" / "что за трек" → radio.py
    if any(phrase in lower for phrase in ("что играет", "что за трек")):
        return
    # "выключи" → radio.py
    if lower in ("стоп", "stop", "пауза", "pause", "дальше", "скип", "next", "skip", "выключи"):
        return

    is_group = message.chat.type in ("group", "supergroup")

    matched_prefix = False

    # Natural language triggers: "включи", "поставь", "хочу послушать", "трек"
    _PREFIXES = ("включи ", "поставь ", "хочу послушать ", "play ", "найди ", "трек ")
    for prefix in _PREFIXES:
        if lower.startswith(prefix):
            text = text[len(prefix):].strip()
            matched_prefix = True
            break

    # In groups: only respond to prefix triggers — ignore links and bare text
    if is_group and not matched_prefix:
        return

    if not text:
        return

    # Intent detection: "random", "рандом", "что-нибудь", "любой трек", etc.
    _RANDOM_INTENTS = (
        "рандом", "случайный", "что-нибудь", "что нибудь", "любой трек",
        "любую песню", "любой", "что угодно", "наугад", "сюрприз",
        "random", "anything", "surprise", "any track", "whatever",
    )
    if text.lower().strip() in _RANDOM_INTENTS:
        track = await get_random_popular_track()
        if track and track.source_id:
            track_info = {
                "video_id": track.source_id,
                "title": track.title or "Unknown",
                "uploader": track.artist or "Unknown",
                "duration": track.duration or 0,
                "duration_fmt": fmt_duration(track.duration) if track.duration else "?:??",
                "source": track.source or "channel",
                "file_id": track.file_id,
            }
            if is_group:
                user = await get_or_create_user(message.from_user)
                status = await message.answer("🎲")
                await _group_auto_play(message, status, user, track_info)
                return
            # DM: still do normal search but with a popular artist
            pass

    await _do_search(message, text)


@router.callback_query(TrackCallback.filter())
async def handle_track_select(
    callback: CallbackQuery, callback_data: TrackCallback
) -> None:
    await callback.answer()

    try:
        user = await get_or_create_user(callback.from_user)
    except Exception:
        await callback.message.answer("⚠️ Сервис временно недоступен. Попробуй снова.")
        return
    lang = user.language
    is_group = callback.message.chat.type in ("group", "supergroup")

    if user.is_banned:
        return

    results = await cache.get_search(callback_data.sid)
    if not results or callback_data.i >= len(results):
        await callback.message.answer(t(lang, "session_expired"))
        return

    track_info = results[callback_data.i]
    _share_q = f"{track_info.get('uploader', '')} - {track_info.get('title', '')}"
    video_id = track_info["video_id"]
    if not await _acquire_download_lock(user.id, video_id):
        return

    default_br = int(await _get_bot_setting("default_bitrate", "192"))
    bitrate = int(user.quality) if user.quality in ("128", "192", "320") else _smart_bitrate(
        track_info.get("source"), track_info.get("duration"), default_br
    )
    _af = _is_ad_free(user)

    try:

        # If track already has a file_id from local DB (channel tracks)
        local_fid = track_info.get("file_id")
        if local_fid:
            caption = _track_caption(lang, track_info, bitrate, ad_free=_af)
            await callback.message.answer_audio(
                audio=local_fid,
                title=track_info["title"],
                performer=track_info["uploader"],
                duration=int(track_info["duration"]) if track_info.get("duration") else None,
                caption=caption,
            )
            tid = await _post_download(user.id, track_info, local_fid, bitrate)
            if is_group:
                await _cleanup_group_search(callback.message.bot, callback_data.sid, callback.message)
            else:
                await callback.message.answer(
                    t(lang, "rate_track"),
                    reply_markup=_feedback_keyboard(tid, _share_q),
                )
            return

        # Проверяем Redis кэш
        file_id = await cache.get_file_id(video_id, bitrate)
        if not file_id:
            try:
                from bot.services.telegram_cache import get_file_id as _tg_get_fid
                file_id = await _tg_get_fid(video_id)
            except Exception:
                pass
        if file_id:
            cache_hits.inc()
            caption = _track_caption(lang, track_info, bitrate, ad_free=_af)
            await callback.message.answer_audio(
                audio=file_id,
                title=track_info["title"],
                performer=track_info["uploader"],
                duration=int(track_info["duration"]) if track_info.get("duration") else None,
                caption=caption,
            )
            tid = await _post_download(user.id, track_info, file_id, bitrate)
            if is_group:
                await _cleanup_group_search(callback.message.bot, callback_data.sid, callback.message)
            else:
                await callback.message.answer(
                    t(lang, "rate_track"),
                    reply_markup=_feedback_keyboard(tid, _share_q),
                )
            return

        status = await callback.message.answer(t(lang, "downloading"))
        await callback.message.bot.send_chat_action(callback.message.chat.id, ChatAction.UPLOAD_DOCUMENT)
        cache_misses.inc()

        progress_cb = _make_progress_cb(status, lang)
        mp3_path: Path | None = None
        _dl_id = uuid.uuid4().hex[:8]

        try:
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
                mp3_path = await download_track(dl_vid, bitrate, progress_cb=progress_cb, dl_id=_dl_id)
            file_size = mp3_path.stat().st_size

            if file_size > settings.MAX_FILE_SIZE and bitrate > 128 and track_info.get("source") not in ("vk", "yandex"):
                cleanup_file(mp3_path)
                mp3_path = None
                await status.edit_text(t(lang, "error_too_large"))
                try:
                    dl_vid_fb = video_id if _is_valid_yt_id(video_id) else (await _resolve_yt_video_id(track_info) or video_id)
                    mp3_path = await download_track(dl_vid_fb, 128, dl_id=_dl_id)
                    bitrate = 128
                    file_size = mp3_path.stat().st_size
                except Exception:
                    mp3_path = None
                    await status.edit_text(t(lang, "error_too_large_final"))
                    return
                if file_size > settings.MAX_FILE_SIZE:
                    cleanup_file(mp3_path)
                    mp3_path = None
                    await status.edit_text(t(lang, "error_too_large_final"))
                    return

            sent = await callback.message.answer_audio(
                audio=FSInputFile(mp3_path),
                title=track_info["title"],
                performer=track_info["uploader"],
                duration=int(track_info["duration"]) if track_info.get("duration") else None,
                caption=_track_caption(lang, track_info, bitrate, ad_free=_af),
            )

            await cache.set_file_id(video_id, sent.audio.file_id, bitrate)
            tid = await _post_download(user.id, track_info, sent.audio.file_id, bitrate)
            await status.delete()
            if is_group:
                await _cleanup_group_search(callback.message.bot, callback_data.sid, callback.message)
            else:
                await callback.message.answer(
                    t(lang, "rate_track"),
                    reply_markup=_feedback_keyboard(tid, _share_q),
                )

        except Exception as e:
            err_msg = str(e)
            logger.error("Download error for %s: %s", video_id, err_msg)
            # C-07: Auto-retry with a different source
            failed_source = track_info.get("source", "youtube")
            retry_query = f"{track_info.get('uploader', '')} {track_info.get('title', '')}".strip()
            if retry_query and failed_source != "youtube":
                try:
                    await status.edit_text(f"⚠️ {failed_source} недоступен, ищу альтернативу...")
                    alt_results = await search_tracks(retry_query, max_results=1, source="youtube")
                    if alt_results:
                        retry_id = uuid.uuid4().hex[:8]
                        retry_path = await download_track(alt_results[0]["video_id"], bitrate, dl_id=retry_id)
                        try:
                            sent = await callback.message.answer_audio(
                                audio=FSInputFile(retry_path),
                                title=track_info["title"],
                                performer=track_info["uploader"],
                                duration=int(track_info["duration"]) if track_info.get("duration") else None,
                                caption=_track_caption(lang, track_info, bitrate, ad_free=_af),
                            )
                            await cache.set_file_id(video_id, sent.audio.file_id, bitrate)
                            tid = await _post_download(user.id, track_info, sent.audio.file_id, bitrate)
                            await status.delete()
                            if not is_group:
                                await callback.message.answer(
                                    t(lang, "rate_track"),
                                    reply_markup=_feedback_keyboard(tid, _share_q),
                                )
                            return
                        finally:
                            cleanup_file(retry_path)
                except Exception as retry_err:
                    logger.debug("Auto-retry also failed: %s", retry_err)
            # Add a retry button so the user can try again
            retry_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="🔄 " + t(lang, "retry_btn"),
                    callback_data=TrackCallback(sid=callback_data.sid, i=callback_data.i).pack(),
                )]
            ])
            await status.edit_text(
                t(lang, _classify_download_error(err_msg)),
                reply_markup=retry_kb,
            )
        finally:
            if mp3_path:
                cleanup_file(mp3_path)
    finally:
        await _release_download_lock(user.id, video_id)


async def _post_download(user_id: int, track_info: dict, file_id: str, bitrate: int) -> int:
    """Records track in DB and listening event. Returns track DB id (0 on DB error)."""
    await increment_request_count(user_id)
    try:
        track = await upsert_track(
            source_id=track_info["video_id"],
            title=track_info["title"],
            artist=track_info["uploader"],
            duration=int(track_info["duration"]) if track_info.get("duration") else None,
            file_id=file_id,
            source=track_info.get("source", "youtube"),
            channel="external",
        )
    except Exception as e:
        logger.warning("_post_download: upsert_track failed: %s", e)
        return 0
    await record_listening_event(
        user_id=user_id,
        track_id=track.id,
        action="play",
        source="search",
    )
    # E-01: Check referral activation on 3rd download
    try:
        from bot.handlers.referral import check_referral_activation
        from bot.models.base import async_session as _async_session2
        from bot.models.user import User as _User2
        async with _async_session2() as session:
            from sqlalchemy import select as _sel2
            u_dl = (await session.execute(_sel2(_User2).where(_User2.id == user_id))).scalar()
            if u_dl:
                await check_referral_activation(user_id, u_dl.request_count)
    except Exception:
        logger.debug("check_referral_activation failed user=%s", user_id, exc_info=True)
    # Auto-update user taste profile every 10 listens
    try:
        from bot.models.base import async_session as _async_session
        from bot.models.user import User as _User
        async with _async_session() as session:
            from sqlalchemy import select as _sel
            u = (await session.execute(_sel(_User).where(_User.id == user_id))).scalar()
            if u and u.request_count and u.request_count % 10 == 0:
                from bot.config import settings as _cfg
                if _cfg.SUPABASE_AI_ENABLED:
                    from bot.services.supabase_ai import supabase_ai
                    try:
                        await supabase_ai.update_profile(user_id)
                    except Exception:
                        logger.debug("supabase_ai.update_profile failed user=%s", user_id, exc_info=True)
                else:
                    from recommender.ai_dj import update_user_profile
                    try:
                        await update_user_profile(user_id)
                    except Exception:
                        logger.debug("update_user_profile failed user=%s", user_id, exc_info=True)
    except Exception as e:
        logger.warning("_post_download: profile update failed: %s", e)
    return track.id


def _feedback_keyboard(track_id: int, share_query: str = "") -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="\u2764\ufe0f",
                callback_data=FeedbackCallback(tid=track_id, act="like").pack(),
            ),
            InlineKeyboardButton(
                text="\ud83d\udc4e",
                callback_data=FeedbackCallback(tid=track_id, act="dislike").pack(),
            ),
            InlineKeyboardButton(
                text="+ \u25b8",
                callback_data=AddToPlCb(tid=track_id).pack(),
            ),
            InlineKeyboardButton(
                text="+ \u25b6",
                callback_data=AddToQueueCb(tid=track_id).pack(),
            ),
        ],
        [
            InlineKeyboardButton(
                text="❤️ +",
                callback_data=FavoriteCb(tid=track_id, act="add").pack(),
            ),
            InlineKeyboardButton(
                text="\ud83d\udcdd \u0422\u0435\u043a\u0441\u0442",
                callback_data=LyricsCb(tid=track_id).pack(),
            ),
            InlineKeyboardButton(
                text="📤",
                callback_data=ShareTrackCb(tid=track_id, act="mk").pack(),
            ),
        ],
        [
            InlineKeyboardButton(
                text="🔁 Похожее",
                callback_data=SimilarCb(tid=track_id).pack(),
            ),
            InlineKeyboardButton(
                text="📸 Story",
                callback_data=StoryCb(tid=track_id).pack(),
            ),
        ],
    ]
    # E-03: Share button
    if share_query:
        rows[1].append(
            InlineKeyboardButton(
                text="\ud83d\udce4",
                switch_inline_query=share_query[:64],
            )
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(FeedbackCallback.filter())
async def handle_feedback(
    callback: CallbackQuery, callback_data: FeedbackCallback
) -> None:
    try:
        user = await get_or_create_user(callback.from_user)
    except Exception:
        await callback.answer()
        return
    await record_listening_event(
        user_id=user.id,
        track_id=callback_data.tid,
        action=callback_data.act,
        source="search",
    )
    emoji = "❤️" if callback_data.act == "like" else "👎"
    await callback.answer(t(user.language, "feedback_recorded", emoji=emoji))
    await callback.message.edit_text(
        t(user.language, "feedback_saved", emoji=emoji), reply_markup=None
    )


@router.callback_query(ShareTrackCb.filter())
async def handle_share_track(callback: CallbackQuery, callback_data: ShareTrackCb) -> None:
    user = await get_or_create_user(callback.from_user)
    lang = user.language

    from bot.models.base import async_session
    from bot.models.track import Track

    async with async_session() as session:
        from sqlalchemy import select as _sel

        track = (
            await session.execute(_sel(Track).where(Track.id == callback_data.tid))
        ).scalar_one_or_none()

    if not track:
        await callback.answer(t(lang, "pl_not_found"), show_alert=True)
        return

    if callback_data.act == "mk":
        try:
            share_id = await create_share_link(
                owner_id=user.id,
                entity_type="track",
                entity_id=track.id,
                ttl_seconds=_TRACK_SHARE_TTL,
            )
        except Exception:
            await callback.answer("⚠️", show_alert=True)
            return

        try:
            from bot.services.leaderboard import add_xp, XP_SHARE
            await add_xp(user.id, XP_SHARE)
        except Exception:
            logger.debug("add_xp share failed user=%s", user.id, exc_info=True)
        bot_me = await callback.bot.me()
        link = f"https://t.me/{bot_me.username}?start=tr_{share_id}"
        await callback.answer()
        await callback.message.answer(
            t(lang, "share_track_created", title=track.title or "?", link=link),
            parse_mode="HTML",
        )
        await track_event(user.id, "track_share", track_id=track.id, share_id=share_id)
        return

    # act == "dl"
    if track.file_id:
        await callback.answer()
        await callback.message.answer_audio(
            audio=track.file_id,
            title=track.title or "Unknown",
            performer=track.artist or "Unknown",
            duration=int(track.duration) if track.duration else None,
            caption=t(lang, "shared_track_caption"),
        )
    else:
        await callback.answer()
        await callback.message.answer(t(lang, "share_track_no_file"))


@router.callback_query(StoryCb.filter())
async def handle_story_card(callback: CallbackQuery, callback_data: StoryCb) -> None:
    """Generate and send a story card for a track."""
    user = await get_or_create_user(callback.from_user)

    from bot.models.base import async_session
    from bot.models.track import Track
    from sqlalchemy import select as _sel

    async with async_session() as session:
        track = (await session.execute(_sel(Track).where(Track.id == callback_data.tid))).scalar_one_or_none()

    if not track:
        await callback.answer("⚠️ Трек не найден", show_alert=True)
        return

    await callback.answer("📸 Генерирую карточку...")
    from bot.services.story_cards import generate_track_card
    from bot.utils import fmt_duration
    from aiogram.types import BufferedInputFile

    card_bytes = generate_track_card(
        artist=track.artist or "Unknown",
        title=track.title or "Unknown",
        track_id=track.id,
        duration=fmt_duration(track.duration or 0),
    )
    if card_bytes:
        await callback.message.answer_photo(
            photo=BufferedInputFile(card_bytes, filename="story.png"),
            caption="📸 Поделись этой карточкой в Stories!",
        )
    else:
        await callback.message.answer("⚠️ Не удалось сгенерировать карточку (Pillow не установлен)")


async def show_shared_track(message: Message, share_id: str) -> None:
    """Display shared track from deep-link /start tr_<share_id>."""
    user = await get_or_create_user(message.from_user)
    lang = user.language

    data = await resolve_share_link(share_id)
    if not data or data.get("entity_type") != "track":
        await message.answer(t(lang, "share_track_expired"))
        return

    track_id = int(data.get("entity_id") or 0)
    await track_event(user.id, "shared_track_open", share_id=share_id, track_id=track_id)

    from bot.models.base import async_session
    from bot.models.track import Track

    async with async_session() as session:
        from sqlalchemy import select as _sel

        track = (
            await session.execute(_sel(Track).where(Track.id == track_id))
        ).scalar_one_or_none()

    if not track:
        await message.answer(t(lang, "share_track_expired"))
        return

    text = t(
        lang,
        "share_track_open_header",
        artist=track.artist or "?",
        title=track.title or "?",
        duration=fmt_duration(track.duration or 0),
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "share_track_download_btn"),
                    callback_data=ShareTrackCb(tid=track.id, act="dl").pack(),
                )
            ]
        ]
    )
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(LyricsCb.filter())
async def handle_lyrics(callback: CallbackQuery, callback_data: LyricsCb) -> None:
    """Fetch and display lyrics for a track."""
    from bot.services.lyrics_provider import get_lyrics
    from bot.models.base import async_session
    from bot.models.track import Track

    try:
        user = await get_or_create_user(callback.from_user)
    except Exception:
        await callback.answer()
        return
    lang = user.language
    await callback.answer()

    async with async_session() as session:
        from sqlalchemy import select as _sel
        result = await session.execute(
            _sel(Track).where(Track.id == callback_data.tid)
        )
        track = result.scalar_one_or_none()

    if not track:
        await callback.message.answer(t(lang, "lyrics_not_found"))
        return

    artist = track.artist or ""
    title = track.title or ""
    lyrics_data = await get_lyrics(artist, title)

    if not lyrics_data or not lyrics_data.get("lines"):
        await callback.message.answer(t(lang, "lyrics_not_found"))
        return

    lines = lyrics_data["lines"]
    url = lyrics_data.get("url", "")
    footer = f"<a href=\"{url}\">{t(lang, 'lyrics_full_link')}</a>" if url else ""
    chunks = _split_long_text_lines(
        header=f"📝 <b>{artist} — {title}</b>",
        lines=lines,
        footer=footer,
        max_len=3900,
    )

    translate_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🌐 Перевод", callback_data=LyrTransCb(tid=callback_data.tid).pack()),
    ]])

    for index, chunk in enumerate(chunks):
        await callback.message.answer(
            chunk,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=translate_kb if index == 0 else None,
        )


@router.callback_query(LyrTransCb.filter())
async def handle_lyrics_translate(callback: CallbackQuery, callback_data: LyrTransCb) -> None:
    """Translate lyrics for a track."""
    from bot.services.lyrics_provider import get_lyrics, translate_lyrics
    from bot.models.base import async_session
    from bot.models.track import Track

    try:
        user = await get_or_create_user(callback.from_user)
    except Exception:
        await callback.answer()
        return
    lang = user.language or "ru"
    await callback.answer()

    async with async_session() as session:
        from sqlalchemy import select as _sel
        result = await session.execute(
            _sel(Track).where(Track.id == callback_data.tid)
        )
        track = result.scalar_one_or_none()

    if not track:
        await callback.message.answer(t(lang, "lyrics_not_found"))
        return

    artist = track.artist or ""
    title_str = track.title or ""
    lyrics_data = await get_lyrics(artist, title_str)

    if not lyrics_data or not lyrics_data.get("lines"):
        await callback.message.answer(t(lang, "lyrics_not_found"))
        return

    target = "ru" if lang != "ru" else "en"
    translated = await translate_lyrics(lyrics_data["lines"], target_lang=target)

    if not translated:
        await callback.message.answer(t(lang, "lyrics_translate_fail"))
        return

    chunks = _split_long_text_lines(
        header=f"🌐 <b>{artist} — {title_str}</b> ({target.upper()})",
        lines=translated,
        max_len=3900,
    )
    for chunk in chunks:
        await callback.message.answer(
            chunk,
            parse_mode="HTML",
        )


def _split_long_text_lines(
    header: str,
    lines: list[str],
    footer: str = "",
    max_len: int = 3900,
) -> list[str]:
    chunks: list[str] = []
    current = (header or "").strip()

    for raw_line in lines or []:
        line = str(raw_line)
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > max_len and current:
            chunks.append(current)
            current = line
        else:
            current = candidate

    if footer:
        candidate = f"{current}\n\n{footer}" if current else footer
        if len(candidate) > max_len and current:
            chunks.append(current)
            current = footer
        else:
            current = candidate

    if current:
        chunks.append(current)

    return chunks


@router.callback_query(SimilarCb.filter())
async def handle_similar(callback: CallbackQuery, callback_data: SimilarCb) -> None:
    """Find similar tracks based on the given track's artist/genre."""
    from bot.models.base import async_session
    from bot.models.track import Track

    try:
        user = await get_or_create_user(callback.from_user)
    except Exception:
        await callback.answer()
        return
    lang = user.language
    await callback.answer()

    async with async_session() as session:
        from sqlalchemy import select as _sel
        track = (
            await session.execute(_sel(Track).where(Track.id == callback_data.tid))
        ).scalar_one_or_none()

    if not track:
        await callback.message.answer(t(lang, "similar_not_found"))
        return

    # Build a search query from artist + genre
    artist = track.artist or ""
    title = track.title or ""
    query = f"{artist} {track.genre or ''}".strip() if artist else title

    if not query:
        await callback.message.answer(t(lang, "similar_not_found"))
        return

    await callback.message.answer(t(lang, "similar_searching"))

    # Search for similar tracks
    results = await search_tracks(query, max_results=5, source="youtube")

    # Also try other sources
    if len(results) < 5:
        try:
            ym = await search_yandex(query, limit=5)
            results.extend(ym)
        except Exception:
            logger.debug("search_yandex fallback failed query=%s", query, exc_info=True)

    if not results:
        await callback.message.answer(t(lang, "similar_not_found"))
        return

    # Deduplicate and remove the original track
    results = deduplicate_results(results)
    results = [r for r in results if r.get("video_id") != track.source_id][:5]

    if not results:
        await callback.message.answer(t(lang, "similar_not_found"))
        return

    session_id = secrets.token_urlsafe(6)
    await cache.store_search(session_id, results)

    buttons = []
    for i, tr in enumerate(results):
        dur = tr.get("duration_fmt", "?:??")
        label = f"♪ {tr.get('uploader', '?')} — {tr.get('title', '?')[:35]} ({dur})"
        buttons.append(
            [InlineKeyboardButton(
                text=label,
                callback_data=TrackCallback(sid=session_id, i=i).pack(),
            )]
        )

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.answer(
        t(lang, "similar_header", artist=artist, title=title[:30]),
        reply_markup=keyboard,
        parse_mode="HTML",
    )
