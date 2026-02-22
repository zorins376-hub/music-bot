import logging
import secrets
from pathlib import Path

from aiogram import Router
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
from bot.db import get_or_create_user, increment_request_count, record_listening_event, upsert_track
from bot.i18n import t
from bot.services.cache import cache
from bot.services.downloader import cleanup_file, download_track, search_tracks

logger = logging.getLogger(__name__)

router = Router()


class TrackCallback(CallbackData, prefix="t"):
    sid: str  # session ID
    i: int    # result index


def _build_results_keyboard(results: list[dict], session_id: str) -> InlineKeyboardMarkup:
    buttons = []
    for i, track in enumerate(results):
        label = f"🎵 {track['uploader']} — {track['title'][:40]} ({track['duration_fmt']})"
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

    allowed, cooldown = await cache.check_rate_limit(
        message.from_user.id, is_premium=user.is_premium
    )
    if not allowed:
        if cooldown > 0:
            await message.answer(t(lang, "rate_limit_cooldown", seconds=cooldown))
        else:
            await message.answer(t(lang, "rate_limit_exceeded"))
        return

    status = await message.answer(t(lang, "searching"))
    results = await search_tracks(query, max_results=5)

    if not results:
        await status.edit_text(t(lang, "no_results"))
        return

    session_id = secrets.token_urlsafe(6)
    await cache.store_search(session_id, results)

    # Записываем запрос в историю
    await record_listening_event(
        user_id=user.id, query=query[:500], action="search", source="search"
    )

    keyboard = _build_results_keyboard(results, session_id)
    await status.edit_text(
        f"<b>Результаты:</b> {query}",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@router.message(Command("search"))
async def cmd_search(message: Message) -> None:
    query = message.text.removeprefix("/search").strip()
    if not query:
        user = await get_or_create_user(message.from_user)
        await message.answer(t(user.language, "search_prompt"))
        return
    await _do_search(message, query)


@router.message(lambda m: m.text and not m.text.startswith("/"))
async def handle_text(message: Message) -> None:
    text = message.text.strip()[:500]
    # "что играет" / "что за трек" → отдельный обработчик в radio.py
    if any(phrase in text.lower() for phrase in ("что играет", "что за трек")):
        return
    # Команды управления радио → radio.py
    if text.lower() in ("стоп", "stop", "пауза", "pause", "дальше", "скип", "next", "skip"):
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

    # Проверяем Redis кэш
    file_id = await cache.get_file_id(video_id, bitrate)
    if file_id:
        await callback.message.answer_audio(
            audio=file_id,
            title=track_info["title"],
            performer=track_info["uploader"],
            duration=track_info.get("duration"),
        )
        await _post_download(user.id, track_info, file_id, bitrate)
        return

    status = await callback.message.answer(t(lang, "downloading"))
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
        )

        await cache.set_file_id(video_id, sent.audio.file_id, bitrate)
        await _post_download(user.id, track_info, sent.audio.file_id, bitrate)
        await status.delete()

    except Exception as e:
        logger.error("Download error for %s: %s", video_id, e)
        await status.edit_text(t(lang, "error_download"))
    finally:
        if mp3_path:
            cleanup_file(mp3_path)


async def _post_download(user_id: int, track_info: dict, file_id: str, bitrate: int) -> None:
    """Записывает трек в БД и событие в историю прослушивания."""
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
