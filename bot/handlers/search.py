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

logger = logging.getLogger(__name__)

router = Router()


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

    # STEP 1: Search local DB (TEQUILA / FULLMOON channels + cached tracks)
    local_tracks = await search_local_tracks(query, limit=5)
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
        session_id = secrets.token_urlsafe(6)
        await cache.store_search(session_id, results)
        await record_listening_event(
            user_id=user.id, query=query[:500], action="search", source="search"
        )
        keyboard = _build_results_keyboard(results, session_id)
        await status.edit_text(
            f"{t(lang, 'found_local')}\n<b>{query}</b>",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return

    # STEP 2: YouTube search (with global query cache)
    results = await cache.get_query_cache(query, "youtube")
    if results is None:
        results = await search_tracks(query, max_results=5, source="youtube")
        if results:
            await cache.set_query_cache(query, results, "youtube")

    # STEP 3: SoundCloud fallback if YouTube found nothing
    if not results:
        results = await cache.get_query_cache(query, "soundcloud")
        if results is None:
            results = await search_tracks(query, max_results=5, source="soundcloud")
            if results:
                await cache.set_query_cache(query, results, "soundcloud")

    if not results:
        await status.edit_text(t(lang, "no_results"))
        return

    session_id = secrets.token_urlsafe(6)
    await cache.store_search(session_id, results)

    await record_listening_event(
        user_id=user.id, query=query[:500], action="search", source="search"
    )

    keyboard = _build_results_keyboard(results, session_id)
    await status.edit_text(
        f"<b>{t(lang, 'search_results')}:</b> {query}",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


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

    # Natural language triggers: "включи", "поставь", "хочу послушать", "трек"
    _PREFIXES = ("включи ", "поставь ", "хочу послушать ", "play ", "найди ", "трек ")
    matched_prefix = False
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

    if user.is_banned:
        return

    results = await cache.get_search(callback_data.sid)
    if not results or callback_data.i >= len(results):
        await callback.message.answer(t(lang, "session_expired"))
        return

    track_info = results[callback_data.i]
    video_id = track_info["video_id"]
    bitrate = int(user.quality) if user.quality in ("128", "192", "320") else settings.DEFAULT_BITRATE

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
        await callback.message.answer(
            t(lang, "rate_track"),
            reply_markup=_feedback_keyboard(tid),
        )
        return

    # Проверяем Redis кэш
    file_id = await cache.get_file_id(video_id, bitrate)
    if file_id:
        caption = _track_caption(lang, track_info, bitrate)
        await callback.message.answer_audio(
            audio=file_id,
            title=track_info["title"],
            performer=track_info["uploader"],
            duration=track_info.get("duration"),
            caption=caption,
        )
        tid = await _post_download(user.id, track_info, file_id, bitrate)
        await callback.message.answer(
            t(lang, "rate_track"),
            reply_markup=_feedback_keyboard(tid),
        )
        return

    status = await callback.message.answer(t(lang, "downloading"))
    await callback.message.bot.send_chat_action(callback.message.chat.id, ChatAction.UPLOAD_DOCUMENT)

    mp3_path: Path | None = None

    try:
        mp3_path = await download_track(video_id, bitrate)
        file_size = mp3_path.stat().st_size

        if file_size > settings.MAX_FILE_SIZE and bitrate > 128:
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
        source="youtube",
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
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❤️",
                    callback_data=FeedbackCallback(tid=track_id, act="like").pack(),
                ),
                InlineKeyboardButton(
                    text="👎",
                    callback_data=FeedbackCallback(tid=track_id, act="dislike").pack(),
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
