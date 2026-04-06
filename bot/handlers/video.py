"""Video search & download — find and send YouTube clips."""

import logging
import secrets
import time
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
from bot.db import get_or_create_user
from bot.i18n import t
from bot.services.cache import cache
from bot.services.downloader import cleanup_file, download_video, search_tracks

logger = logging.getLogger(__name__)
router = Router()

_LOGO = "◉ <b>BLACK ROOM</b>"
_MAX_VIDEO_RESULTS = 5
_VIDEO_QUALITIES = ["360", "480", "720"]


# ── Callback Data ────────────────────────────────────────────────────────

class VideoCb(CallbackData, prefix="vs"):
    """Video search result selection."""
    sid: str   # session id
    i: int     # result index


class VideoQualCb(CallbackData, prefix="vq"):
    """Video quality selection."""
    sid: str   # session id
    i: int     # result index
    q: str     # quality: 360/480/720


# ── State: waiting for video query ──────────────────────────────────────

# user_id → timestamp when they entered video wait mode
_video_wait: dict[int, float] = {}


# ── UI builders ──────────────────────────────────────────────────────────

def _build_video_results_kb(results: list[dict], session_id: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for i, tr in enumerate(results):
        dur = tr.get("duration_fmt", "?:??")
        label = f"🎬 {tr['uploader']} — {tr['title'][:35]} ({dur})"
        if len(label) > 60:
            label = label[:57] + "..."
        rows.append([
            InlineKeyboardButton(
                text=label,
                callback_data=VideoCb(sid=session_id, i=i).pack(),
            )
        ])
    rows.append([InlineKeyboardButton(text="◁ Меню", callback_data="action:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _build_quality_kb(session_id: str, idx: int) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="360p", callback_data=VideoQualCb(sid=session_id, i=idx, q="360").pack()),
            InlineKeyboardButton(text="480p", callback_data=VideoQualCb(sid=session_id, i=idx, q="480").pack()),
            InlineKeyboardButton(text="720p", callback_data=VideoQualCb(sid=session_id, i=idx, q="720").pack()),
        ],
        [InlineKeyboardButton(text="◁ Назад", callback_data=f"vback:{session_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Handlers ─────────────────────────────────────────────────────────────

@router.message(Command("video"))
async def cmd_video(message: Message) -> None:
    query = message.text.removeprefix("/video").strip()[:500]
    if query:
        await _do_video_search(message, query)
    else:
        _video_wait[message.from_user.id] = time.monotonic()
        await message.answer(
            f"{_LOGO}\n\n🎬 <b>Поиск видео</b>\n\nНапиши название клипа или исполнителя:",
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data == "action:video")
async def handle_video_button(callback: CallbackQuery) -> None:
    await callback.answer()
    _video_wait[callback.from_user.id] = time.monotonic()
    try:
        await callback.message.edit_text(
            f"{_LOGO}\n\n🎬 <b>Поиск видео</b>\n\nНапиши название клипа или исполнителя:",
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            f"{_LOGO}\n\n🎬 <b>Поиск видео</b>\n\nНапиши название клипа или исполнителя:",
            parse_mode="HTML",
        )


@router.message(lambda m: m.text and m.chat.type == "private" and not m.text.startswith("/") and m.from_user and m.from_user.id in _video_wait)
async def handle_video_query(message: Message) -> None:
    _video_wait.pop(message.from_user.id, None)
    # Purge stale entries older than 5 minutes
    now = time.monotonic()
    stale = [uid for uid, ts in _video_wait.items() if now - ts > 300]
    for uid in stale:
        _video_wait.pop(uid, None)
    query = message.text.strip()[:500]
    if query:
        await _do_video_search(message, query)


async def _do_video_search(message: Message, query: str) -> None:
    user = await get_or_create_user(message.from_user)
    lang = user.language

    if user.is_banned:
        return

    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    status = await message.answer("🎬 Ищу клипы...")

    # Search YouTube only (videos)
    results = await search_tracks(query, max_results=_MAX_VIDEO_RESULTS, source="youtube")
    if not results:
        await status.edit_text("Клипы не найдены. Попробуй другой запрос.")
        return

    session_id = secrets.token_urlsafe(6)
    await cache.store_search(session_id, results)
    kb = _build_video_results_kb(results, session_id)
    await status.edit_text(
        f"{_LOGO}\n\n🎬 <b>Видео:</b> {query}\n\n<i>Выбери клип:</i>",
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.callback_query(VideoCb.filter())
async def handle_video_select(callback: CallbackQuery, callback_data: VideoCb) -> None:
    """User picked a video — show quality picker."""
    await callback.answer()

    results = await cache.get_search(callback_data.sid)
    if not results or callback_data.i >= len(results):
        await callback.message.answer("Сессия истекла. Повтори поиск /video")
        return

    tr = results[callback_data.i]
    dur = tr.get("duration_fmt", "?:??")
    kb = _build_quality_kb(callback_data.sid, callback_data.i)
    try:
        await callback.message.edit_text(
            f"{_LOGO}\n\n🎬 <b>{tr['uploader']} — {tr['title']}</b>\n"
            f"◷ {dur}\n\nВыбери качество:",
            reply_markup=kb,
            parse_mode="HTML",
        )
    except Exception:
        logger.debug("Failed to edit video quality selection message", exc_info=True)


@router.callback_query(lambda c: c.data and c.data.startswith("vback:"))
async def handle_video_back(callback: CallbackQuery) -> None:
    """Back to video results list."""
    await callback.answer()
    session_id = callback.data.split("vback:", 1)[1]
    results = await cache.get_search(session_id)
    if not results:
        await callback.message.answer("Сессия истекла. Повтори поиск /video")
        return
    kb = _build_video_results_kb(results, session_id)
    try:
        await callback.message.edit_text(
            f"{_LOGO}\n\n🎬 <b>Результаты</b>\n\n<i>Выбери клип:</i>",
            reply_markup=kb,
            parse_mode="HTML",
        )
    except Exception:
        logger.debug("Failed to edit video results message", exc_info=True)


@router.callback_query(VideoQualCb.filter())
async def handle_video_download(callback: CallbackQuery, callback_data: VideoQualCb) -> None:
    """Download and send video in chosen quality."""
    await callback.answer("⏳ Скачиваю клип...")

    user = await get_or_create_user(callback.from_user)
    lang = user.language

    results = await cache.get_search(callback_data.sid)
    if not results or callback_data.i >= len(results):
        await callback.message.answer("Сессия истекла. Повтори поиск /video")
        return

    tr = results[callback_data.i]
    video_id = tr["video_id"]
    quality = callback_data.q

    # Check Redis cache for video file_id
    cache_key = f"vid:{video_id}:{quality}"
    cached_fid = await cache.redis.get(cache_key)
    if cached_fid:
        fid = cached_fid if isinstance(cached_fid, str) else cached_fid.decode()
        caption = f"🎬 {tr['uploader']} — {tr['title']}\n◷ {tr.get('duration_fmt', '?:??')} · {quality}p"
        await callback.message.answer_video(
            video=fid,
            caption=caption,
            supports_streaming=True,
        )
        return

    status = await callback.message.answer("🎬 Скачиваю клип... Это может занять до минуты.")
    await callback.message.bot.send_chat_action(callback.message.chat.id, ChatAction.UPLOAD_VIDEO)

    video_path: Path | None = None
    try:
        video_path = await download_video(video_id, quality)
        file_size = video_path.stat().st_size

        # Telegram limit: 50 MB for bots
        if file_size > 50 * 1024 * 1024:
            if quality != "360":
                await status.edit_text("△ Клип слишком большой. Пробую 360p...")
                cleanup_file(video_path)
                video_path = await download_video(video_id, "360")
                quality = "360"
                file_size = video_path.stat().st_size
                if file_size > 50 * 1024 * 1024:
                    await status.edit_text("Клип слишком длинный/большой для Telegram (макс 50 МБ).")
                    return
            else:
                await status.edit_text("Клип слишком длинный/большой для Telegram (макс 50 МБ).")
                return

        caption = f"🎬 {tr['uploader']} — {tr['title']}\n◷ {tr.get('duration_fmt', '?:??')} · {quality}p"
        sent = await callback.message.answer_video(
            video=FSInputFile(video_path),
            caption=caption,
            duration=int(tr["duration"]) if tr.get("duration") else None,
            supports_streaming=True,
        )

        # Cache file_id for 30 days
        if sent.video:
            await cache.redis.setex(cache_key, 30 * 24 * 3600, sent.video.file_id)

        await status.delete()

    except Exception as e:
        err = str(e)
        logger.error("Video download error for %s: %s", video_id, err)
        if "Sign in to confirm your age" in err:
            await status.edit_text("△ Этот клип имеет возрастное ограничение (18+).")
        else:
            await status.edit_text("Не удалось скачать клип. Попробуй другой.")
    finally:
        if video_path:
            cleanup_file(video_path)
