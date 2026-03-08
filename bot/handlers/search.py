import asyncio
import logging
import secrets
import time
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
from bot.db import get_or_create_user, get_popular_titles, increment_request_count, record_listening_event, search_local_tracks, upsert_track
from bot.i18n import t
from bot.services.cache import cache
from bot.services.downloader import cleanup_file, download_track, search_tracks, is_youtube_url, extract_youtube_video_id, resolve_youtube_url
from bot.services.spotify_provider import is_spotify_url, resolve_spotify_url, search_spotify
from bot.services.vk_provider import download_vk, search_vk
from bot.services.yandex_provider import download_yandex, search_yandex, is_yandex_music_url, resolve_yandex_url
from bot.services.metrics import cache_hits, cache_misses, requests_total
from bot.services.search_engine import deduplicate_results, suggest_query
from bot.callbacks import TrackCallback, FeedbackCallback, AddToPlCb, AddToQueueCb, LyricsCb
from bot.utils import fmt_duration

logger = logging.getLogger(__name__)

router = Router()


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


async def _safe_edit(msg, text: str) -> None:
    """Edit message text, ignoring any Telegram errors."""
    try:
        await msg.edit_text(text)
    except Exception:
        pass


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

# session_id → {chat_id, user_msg_id, status_msg_id}
_group_sessions: dict[str, dict] = {}


async def _schedule_group_cleanup(bot, session_id: str) -> None:
    """Delete search messages in group if no track selected within timeout."""
    await asyncio.sleep(_GROUP_CLEANUP_SEC)
    info = _group_sessions.pop(session_id, None)
    if not info:
        return
    for mid in (info.get("status_msg_id"), info.get("user_msg_id")):
        if mid:
            try:
                await bot.delete_message(info["chat_id"], mid)
            except Exception:
                pass


async def _cleanup_group_search(bot, session_id: str, results_msg: Message) -> None:
    """After track is selected in group: delete original message + search results."""
    info = _group_sessions.pop(session_id, None)
    # Delete the search results message (the inline keyboard message)
    try:
        await results_msg.delete()
    except Exception:
        pass
    if not info:
        return
    # Delete the original user message
    if info.get("user_msg_id"):
        try:
            await bot.delete_message(info["chat_id"], info["user_msg_id"])
        except Exception:
            pass


# TrackCallback, FeedbackCallback, AddToPlCb imported from bot.callbacks


def _track_caption(lang: str, track_info: dict, bitrate: int) -> str:
    """Build caption line: ◷ 3:42 · 192 kbps · 2019"""
    dur = track_info.get("duration_fmt") or "?:??"
    year = track_info.get("upload_year")
    year_str = f" · {year}" if year else ""
    return t(lang, "track_caption", duration=dur, bitrate=bitrate, year=year_str)


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
    if local_tracks:
        results = []
        for tr in local_tracks:
            results.append({
                "video_id": tr.source_id,
                "title": tr.title or "Unknown",
                "uploader": tr.artist or "Unknown",
                "duration": tr.duration or 0,
                "duration_fmt": _fmt_duration(tr.duration) if tr.duration else "?:??",
                "source": tr.source or "channel",
                "file_id": tr.file_id,
            })
        await record_listening_event(
            user_id=user.id, query=query[:500], action="search", source="search"
        )

        # Groups: auto-play first track immediately
        if is_group:
            await _group_auto_play(message, status, user, results[0])
            return

        session_id = secrets.token_urlsafe(6)
        await cache.store_search(session_id, results)
        keyboard = _build_results_keyboard(results, session_id)
        await status.edit_text(
            f"{_SEARCH_LOGO}\n\n"
            f"{t(lang, 'found_local')}\n"
            f"\u25b8 <b>{query}</b> ({len(results)})",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return

    # STEP 2: Parallel external search — Yandex + Spotify + SoundCloud + VK + YouTube
    async def _search_source(source: str, search_fn, limit: int) -> list[dict]:
        """Search a single source with cache and 8s timeout."""
        try:
            cached = await cache.get_query_cache(query, source)
            if cached is not None:
                return cached
            res = await asyncio.wait_for(search_fn(query, limit=limit), timeout=8)
            if res:
                await cache.set_query_cache(query, res, source)
                requests_total.labels(source=source).inc()
            return res or []
        except Exception:
            logger.debug("search source %s failed", source, exc_info=True)
            return []

    async def _search_sc(query_: str, limit: int = 5) -> list[dict]:
        return await search_tracks(query_, max_results=limit, source="soundcloud")

    async def _search_yt(query_: str, limit: int = 5) -> list[dict]:
        return await search_tracks(query_, max_results=limit, source="youtube")

    tasks = [
        _search_source("yandex", search_yandex, max_results),
        _search_source("spotify", search_spotify, max_results),
        _search_source("soundcloud", _search_sc, max_results),
        _search_source("vk", search_vk, max_results),
        _search_source("youtube", _search_yt, max_results),
    ]
    source_results = await asyncio.gather(*tasks)
    all_results: list[dict] = []
    for batch in source_results:
        all_results.extend(batch)

    # Deduplicate across sources
    results = deduplicate_results(all_results)[:max_results] if all_results else []

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

    # Groups: auto-play first track immediately
    if is_group:
        await _group_auto_play(message, status, user, results[0])
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


async def _download_spotify_track(track_info: dict, bitrate: int) -> Path:
    """Download a Spotify track via Yandex Music (preferred) or YouTube fallback."""
    query = track_info.get("yt_query") or f"{track_info['uploader']} - {track_info['title']}"
    video_id = track_info["video_id"]

    # Try Yandex first — best quality
    ym_results = await search_yandex(query, limit=1)
    if ym_results and ym_results[0].get("ym_track_id"):
        dest = settings.DOWNLOAD_DIR / f"{video_id}.mp3"
        await download_yandex(ym_results[0]["ym_track_id"], dest, bitrate)
        return dest

    # Fallback: search YouTube and download
    yt_results = await search_tracks(query, max_results=1, source="youtube")
    if yt_results:
        return await download_track(yt_results[0]["video_id"], bitrate)

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
    local_fid = track_info.get("file_id")
    if local_fid:
        caption = _track_caption(lang, track_info, bitrate)
        await message.answer_audio(
            audio=local_fid,
            title=track_info["title"],
            performer=track_info["uploader"],
            duration=track_info.get("duration"),
            caption=caption,
        )
        await _post_download(user.id, track_info, local_fid, bitrate)
        await _delete_msgs(message.bot, message.chat.id, [status.message_id, message.message_id])
        return

    # Redis cache
    file_id = await cache.get_file_id(video_id, bitrate)
    if file_id:
        caption = _track_caption(lang, track_info, bitrate)
        await message.answer_audio(
            audio=file_id,
            title=track_info["title"],
            performer=track_info["uploader"],
            duration=track_info.get("duration"),
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
        if track_info.get("source") == "yandex" and track_info.get("ym_track_id"):
            mp3_path = settings.DOWNLOAD_DIR / f"{video_id}.mp3"
            await download_yandex(track_info["ym_track_id"], mp3_path, bitrate, token=track_info.get("_ym_token"))
        elif track_info.get("source") == "vk" and track_info.get("vk_url"):
            mp3_path = settings.DOWNLOAD_DIR / f"{video_id}.mp3"
            await download_vk(track_info["vk_url"], mp3_path)
        elif track_info.get("source") == "spotify":
            mp3_path = await _download_spotify_track(track_info, bitrate)
        else:
            mp3_path = await download_track(video_id, bitrate)
        file_size = mp3_path.stat().st_size
        if file_size > settings.MAX_FILE_SIZE and bitrate > 128 and track_info.get("source") not in ("vk", "yandex"):
            cleanup_file(mp3_path)
            mp3_path = None
            try:
                mp3_path = await download_track(video_id, 128)
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
            duration=track_info.get("duration"),
            caption=_track_caption(lang, track_info, bitrate),
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
                pass


# fmt_duration imported from bot.utils
_fmt_duration = fmt_duration


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

    # Handle @bot_username mentions in groups — simple text-based detection
    if is_group:
        bot_me = await message.bot.me()
        if bot_me.username:
            at_tag = f"@{bot_me.username}"
            # Case-insensitive check
            idx = lower.find(at_tag.lower())
            if idx != -1:
                text = (text[:idx] + text[idx + len(at_tag):]).strip()
                lower = text.lower()
                matched_prefix = True

    # Natural language triggers: "включи", "поставь", "хочу послушать", "трек"
    _PREFIXES = ("включи ", "поставь ", "хочу послушать ", "play ", "найди ", "трек ")
    if not matched_prefix:
        for prefix in _PREFIXES:
            if lower.startswith(prefix):
                text = text[len(prefix):].strip()
                matched_prefix = True
                break

    # In groups: auto-convert YouTube/Spotify/Yandex links even without trigger prefix
    if is_group and not matched_prefix:
        if is_youtube_url(text) or is_spotify_url(text) or is_yandex_music_url(text):
            await _do_search(message, text)
            return
        return

    if not text:
        return

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
    video_id = track_info["video_id"]
    default_br = int(await _get_bot_setting("default_bitrate", "192"))
    bitrate = int(user.quality) if user.quality in ("128", "192", "320") else _smart_bitrate(
        track_info.get("source"), track_info.get("duration"), default_br
    )

    # If track already has a file_id from local DB (channel tracks)
    local_fid = track_info.get("file_id")
    if local_fid:
        caption = _track_caption(lang, track_info, bitrate)
        await callback.message.answer_audio(
            audio=local_fid,
            title=track_info["title"],
            performer=track_info["uploader"],
            duration=track_info.get("duration"),
            caption=caption,
        )
        tid = await _post_download(user.id, track_info, local_fid, bitrate)
        if is_group:
            await _cleanup_group_search(callback.message.bot, callback_data.sid, callback.message)
        else:
            await callback.message.answer(
                t(lang, "rate_track"),
                reply_markup=_feedback_keyboard(tid),
            )
        return

    # Проверяем Redis кэш
    file_id = await cache.get_file_id(video_id, bitrate)
    if file_id:
        cache_hits.inc()
        caption = _track_caption(lang, track_info, bitrate)
        await callback.message.answer_audio(
            audio=file_id,
            title=track_info["title"],
            performer=track_info["uploader"],
            duration=track_info.get("duration"),
            caption=caption,
        )
        tid = await _post_download(user.id, track_info, file_id, bitrate)
        if is_group:
            await _cleanup_group_search(callback.message.bot, callback_data.sid, callback.message)
        else:
            await callback.message.answer(
                t(lang, "rate_track"),
                reply_markup=_feedback_keyboard(tid),
            )
        return

    status = await callback.message.answer(t(lang, "downloading"))
    await callback.message.bot.send_chat_action(callback.message.chat.id, ChatAction.UPLOAD_DOCUMENT)
    cache_misses.inc()

    progress_cb = _make_progress_cb(status, lang)
    mp3_path: Path | None = None

    try:
        if track_info.get("source") == "yandex" and track_info.get("ym_track_id"):
            mp3_path = settings.DOWNLOAD_DIR / f"{video_id}.mp3"
            await download_yandex(track_info["ym_track_id"], mp3_path, bitrate, token=track_info.get("_ym_token"))
        elif track_info.get("source") == "vk" and track_info.get("vk_url"):
            mp3_path = settings.DOWNLOAD_DIR / f"{video_id}.mp3"
            await download_vk(track_info["vk_url"], mp3_path)
        elif track_info.get("source") == "spotify":
            mp3_path = await _download_spotify_track(track_info, bitrate)
        else:
            mp3_path = await download_track(video_id, bitrate, progress_cb=progress_cb)
        file_size = mp3_path.stat().st_size

        if file_size > settings.MAX_FILE_SIZE and bitrate > 128 and track_info.get("source") not in ("vk", "yandex"):
            cleanup_file(mp3_path)
            mp3_path = None
            await status.edit_text(t(lang, "error_too_large"))
            try:
                mp3_path = await download_track(video_id, 128)
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
            duration=track_info.get("duration"),
            caption=_track_caption(lang, track_info, bitrate),
        )

        await cache.set_file_id(video_id, sent.audio.file_id, bitrate)
        tid = await _post_download(user.id, track_info, sent.audio.file_id, bitrate)
        await status.delete()
        if is_group:
            await _cleanup_group_search(callback.message.bot, callback_data.sid, callback.message)
        else:
            await callback.message.answer(
                t(lang, "rate_track"),
                reply_markup=_feedback_keyboard(tid),
            )

    except Exception as e:
        err_msg = str(e)
        logger.error("Download error for %s: %s", video_id, err_msg)
        await status.edit_text(t(lang, _classify_download_error(err_msg)))
    finally:
        if mp3_path:
            cleanup_file(mp3_path)


async def _post_download(user_id: int, track_info: dict, file_id: str, bitrate: int) -> int:
    """Records track in DB and listening event. Returns track DB id (0 on DB error)."""
    await increment_request_count(user_id)
    try:
        track = await upsert_track(
            source_id=track_info["video_id"],
            title=track_info["title"],
            artist=track_info["uploader"],
            duration=track_info.get("duration"),
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
    # Auto-update user taste profile every 10 listens
    try:
        from bot.models.base import async_session as _async_session
        from bot.models.user import User as _User
        async with _async_session() as session:
            from sqlalchemy import select as _sel
            u = (await session.execute(_sel(_User).where(_User.id == user_id))).scalar()
            if u and u.request_count and u.request_count % 10 == 0:
                from recommender.ai_dj import update_user_profile
                try:
                    await update_user_profile(user_id)
                except Exception:
                    pass
    except Exception as e:
        logger.warning("_post_download: profile update failed: %s", e)
    return track.id


def _feedback_keyboard(track_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
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
                    text="\ud83d\udcdd \u0422\u0435\u043a\u0441\u0442",
                    callback_data=LyricsCb(tid=track_id).pack(),
                ),
            ],
        ]
    )


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
    text_parts = [f"📝 <b>{artist} — {title}</b>\n"]
    text_parts.extend(lines)
    if url:
        text_parts.append(f"\n<a href=\"{url}\">{t(lang, 'lyrics_full_link')}</a>")

    await callback.message.answer(
        "\n".join(text_parts),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
