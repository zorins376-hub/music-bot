import asyncio
import logging
import secrets
from pathlib import Path

from aiogram import Router
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.config import settings
from bot.db import get_or_create_user, increment_request_count, record_listening_event, search_local_tracks, upsert_track
from bot.i18n import t
from bot.services.cache import cache
from bot.services.downloader import cleanup_file, download_track, is_spotify_url, resolve_spotify, search_tracks
from bot.services.vk_provider import download_vk, search_vk
from bot.services.yandex_provider import download_yandex, search_yandex
from bot.services.metrics import cache_hits, cache_misses, requests_total

logger = logging.getLogger(__name__)

router = Router()

# Group chat auto-cleanup timeout (seconds)
_GROUP_CLEANUP_SEC = 60

# Search result limits
_MAX_RESULTS_GROUP = 1      # In groups — just one track


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


class TrackCallback(CallbackData, prefix="t"):
    sid: str  # session ID
    i: int    # result index


class FeedbackCallback(CallbackData, prefix="fb"):
    tid: int    # track DB id
    act: str    # like / dislike


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
    user = await get_or_create_user(message.from_user)
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

    # Spotify link → extract metadata → YouTube search
    if is_spotify_url(query):
        status = await message.answer(t(lang, "spotify_detected"))
        resolved = await resolve_spotify(query)
        if resolved:
            query = resolved
        else:
            await status.edit_text(t(lang, "no_results"))
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

    # STEP 2: Яндекс.Музыка — 320 kbps, если токен есть
    results = await search_yandex(query, limit=max_results)
    if results:
        requests_total.labels(source="yandex").inc()

    # STEP 3: YouTube search (with global query cache)
    if not results:
        results = await cache.get_query_cache(query, "youtube")
        if results is None:
            results = await search_tracks(query, max_results=max_results, source="youtube")
            if results:
                await cache.set_query_cache(query, results, "youtube")

    # STEP 4: SoundCloud fallback if YouTube found nothing
    if not results:
        results = await cache.get_query_cache(query, "soundcloud")
        if results is None:
            results = await search_tracks(query, max_results=max_results, source="soundcloud")
            if results:
                await cache.set_query_cache(query, results, "soundcloud")

    # STEP 5: VK fallback — rare tracks not on YouTube/SoundCloud
    if not results:
        results = await search_vk(query, limit=max_results)
        if results:
            requests_total.labels(source="vk").inc()

    if not results:
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
    _src = results[0].get("source", "youtube")
    source_tag = {"soundcloud": "▸ SoundCloud", "vk": "▸ VK Music", "yandex": "▸ Яндекс.Музыка"}.get(_src, "▸ YouTube")
    await status.edit_text(
        f"{_SEARCH_LOGO}\n\n"
        f"<b>{t(lang, 'search_results')}:</b> {query}\n"
        f"{source_tag} \u00b7 {len(results)} \u0442\u0440\u0435\u043a\u043e\u0432",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


async def _group_auto_play(
    message: Message, status: Message, user, track_info: dict
) -> None:
    """In groups: download and send the first track immediately, then clean up."""
    lang = user.language
    default_br = int(await _get_bot_setting("default_bitrate", "192"))
    bitrate = int(user.quality) if user.quality in ("128", "192", "320") else default_br
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
            await download_yandex(track_info["ym_track_id"], mp3_path, bitrate)
        elif track_info.get("source") == "vk" and track_info.get("vk_url"):
            mp3_path = settings.DOWNLOAD_DIR / f"{video_id}.mp3"
            await download_vk(track_info["vk_url"], mp3_path)
        else:
            mp3_path = await download_track(video_id, bitrate)
        file_size = mp3_path.stat().st_size
        if file_size > settings.MAX_FILE_SIZE and bitrate > 128 and track_info.get("source") not in ("vk", "yandex"):
            cleanup_file(mp3_path)
            mp3_path = None
            mp3_path = await download_track(video_id, 128)
            bitrate = 128
            file_size = mp3_path.stat().st_size
            if file_size > settings.MAX_FILE_SIZE:
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
        if "Sign in to confirm your age" in err_msg:
            await status.edit_text(t(lang, "error_age_restricted"))
        else:
            await status.edit_text(t(lang, "error_download"))
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


def _fmt_duration(seconds: int | None) -> str:
    if not seconds:
        return "?:??"
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


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

    # In groups: only respond to trigger words, ignore random messages
    if is_group and not matched_prefix:
        return

    if not text:
        return

    await _do_search(message, text)


@router.callback_query(TrackCallback.filter())
async def handle_track_select(
    callback: CallbackQuery, callback_data: TrackCallback
) -> None:
    await callback.answer()

    user = await get_or_create_user(callback.from_user)
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
    bitrate = int(user.quality) if user.quality in ("128", "192", "320") else default_br

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

    mp3_path: Path | None = None

    try:
        if track_info.get("source") == "yandex" and track_info.get("ym_track_id"):
            mp3_path = settings.DOWNLOAD_DIR / f"{video_id}.mp3"
            await download_yandex(track_info["ym_track_id"], mp3_path, bitrate)
        elif track_info.get("source") == "vk" and track_info.get("vk_url"):
            mp3_path = settings.DOWNLOAD_DIR / f"{video_id}.mp3"
            await download_vk(track_info["vk_url"], mp3_path)
        else:
            mp3_path = await download_track(video_id, bitrate)
        file_size = mp3_path.stat().st_size

        if file_size > settings.MAX_FILE_SIZE and bitrate > 128 and track_info.get("source") not in ("vk", "yandex"):
            cleanup_file(mp3_path)
            mp3_path = None
            await status.edit_text(t(lang, "error_too_large"))
            mp3_path = await download_track(video_id, 128)
            bitrate = 128
            file_size = mp3_path.stat().st_size
            if file_size > settings.MAX_FILE_SIZE:
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
        if "Sign in to confirm your age" in err_msg:
            await status.edit_text(t(lang, "error_age_restricted"))
        else:
            await status.edit_text(t(lang, "error_download"))
    finally:
        if mp3_path:
            cleanup_file(mp3_path)


async def _post_download(user_id: int, track_info: dict, file_id: str, bitrate: int) -> int:
    """Записывает трек в БД и событие в историю прослушивания. Returns track DB id."""
    await increment_request_count(user_id)
    track = await upsert_track(
        source_id=track_info["video_id"],
        title=track_info["title"],
        artist=track_info["uploader"],
        duration=track_info.get("duration"),
        file_id=file_id,
        source=track_info.get("source", "youtube"),
        channel="external",
    )
    await record_listening_event(
        user_id=user_id,
        track_id=track.id,
        action="play",
        source="search",
    )
    # Auto-update user taste profile every 10 listens
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
    return track.id


def _feedback_keyboard(track_id: int) -> InlineKeyboardMarkup:
    from bot.handlers.playlist import AddToPlCb
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
            ]
        ]
    )


@router.callback_query(FeedbackCallback.filter())
async def handle_feedback(
    callback: CallbackQuery, callback_data: FeedbackCallback
) -> None:
    user = await get_or_create_user(callback.from_user)
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
