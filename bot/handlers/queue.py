"""
queue.py — Listening queue stored in Redis (TTL 2h, max 50 tracks).

Commands: /queue, /next
Callback buttons: ⏭ Next, 🔀 Shuffle, ❌ Clear
"""
import json
import random

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.callbacks import QueueCb, AddToQueueCb
from bot.db import get_or_create_user
from bot.i18n import t
from bot.services.cache import cache
from bot.utils import fmt_duration

router = Router()

_MAX_QUEUE = 50
_QUEUE_TTL = 7200  # 2 hours


def _queue_key(user_id: int) -> str:
    return f"queue:{user_id}"


async def _get_queue(user_id: int) -> list[dict]:
    try:
        data = await cache.redis.get(_queue_key(user_id))
        return json.loads(data) if data else []
    except Exception:
        return []


async def _set_queue(user_id: int, items: list[dict]) -> None:
    try:
        await cache.redis.setex(
            _queue_key(user_id), _QUEUE_TTL,
            json.dumps(items, ensure_ascii=False),
        )
    except Exception:
        pass


async def add_to_queue(user_id: int, track: dict, lang: str = "ru") -> str:
    """Add a track dict to user's queue. Returns status message."""
    items = await _get_queue(user_id)
    if len(items) >= _MAX_QUEUE:
        return t(lang, "queue_full")
    items.append(track)
    await _set_queue(user_id, items)
    title = f"{track.get('uploader', '?')} — {track.get('title', '?')}"
    return t(lang, "queue_added").format(title=title)


def _queue_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⏭ Далее", callback_data=QueueCb(act="next").pack()),
            InlineKeyboardButton(text="🔀 Перемешать", callback_data=QueueCb(act="shuf").pack()),
            InlineKeyboardButton(text="❌ Очистить", callback_data=QueueCb(act="clr").pack()),
        ]
    ])


async def _show_queue(message_or_cb, user_id: int, lang: str) -> None:
    """Display the current queue."""
    items = await _get_queue(user_id)
    if not items:
        text = t(lang, "queue_empty")
        if isinstance(message_or_cb, CallbackQuery):
            await message_or_cb.answer(text, show_alert=True)
        else:
            await message_or_cb.answer(text)
        return

    lines = [t(lang, "queue_header").format(count=len(items))]
    for i, tr in enumerate(items[:20], 1):
        dur = tr.get("duration_fmt") or fmt_duration(tr.get("duration"))
        lines.append(f"{i}. {tr.get('uploader', '?')} — {tr.get('title', '?')[:40]} ({dur})")
    if len(items) > 20:
        lines.append(f"... и ещё {len(items) - 20}")

    text = "\n".join(lines)
    kb = _queue_keyboard()

    if isinstance(message_or_cb, CallbackQuery):
        try:
            await message_or_cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await message_or_cb.message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await message_or_cb.answer(text, reply_markup=kb, parse_mode="HTML")


@router.message(Command("queue"))
async def cmd_queue(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    await _show_queue(message, user.id, user.language)


@router.message(Command("next"))
async def cmd_next(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    lang = user.language
    items = await _get_queue(user.id)
    if not items:
        await message.answer(t(lang, "queue_no_next"))
        return

    track = items.pop(0)
    await _set_queue(user.id, items)

    # Send cached audio if file_id available
    file_id = track.get("file_id")
    if file_id:
        title = track.get("title", "Unknown")
        artist = track.get("uploader", "Unknown")
        dur = int(track["duration"]) if track.get("duration") else 0
        await message.answer_audio(
            audio=file_id,
            title=title,
            performer=artist,
            duration=dur,
        )
    else:
        # No cached file — tell user to search
        title = f"{track.get('uploader', '?')} — {track.get('title', '?')}"
        await message.answer(f"⏭ {title}\n\n🔍", reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(
                    text=f"🔍 {title[:40]}",
                    switch_inline_query_current_chat=f"{track.get('uploader', '')} {track.get('title', '')}".strip(),
                )
            ]]
        ))


@router.callback_query(QueueCb.filter())
async def handle_queue_cb(callback: CallbackQuery, callback_data: QueueCb) -> None:
    user = await get_or_create_user(callback.from_user)
    lang = user.language
    act = callback_data.act

    if act == "next":
        items = await _get_queue(user.id)
        if not items:
            await callback.answer(t(lang, "queue_no_next"), show_alert=True)
            return
        track = items.pop(0)
        await _set_queue(user.id, items)
        await callback.answer()

        file_id = track.get("file_id")
        if file_id:
            await callback.message.answer_audio(
                audio=file_id,
                title=track.get("title", "Unknown"),
                performer=track.get("uploader", "Unknown"),
                duration=int(track["duration"]) if track.get("duration") else 0,
            )
        else:
            title = f"{track.get('uploader', '?')} — {track.get('title', '?')}"
            await callback.message.answer(f"⏭ {title}")
        # Refresh queue view
        await _show_queue(callback, user.id, lang)

    elif act == "shuf":
        items = await _get_queue(user.id)
        if items:
            random.shuffle(items)
            await _set_queue(user.id, items)
        await callback.answer(t(lang, "queue_shuffled"))
        await _show_queue(callback, user.id, lang)

    elif act == "clr":
        await _set_queue(user.id, [])
        await callback.answer(t(lang, "queue_cleared"))
        await _show_queue(callback, user.id, lang)

    elif act == "show":
        await callback.answer()
        await _show_queue(callback, user.id, lang)

    else:
        await callback.answer()


@router.callback_query(AddToQueueCb.filter())
async def handle_add_to_queue(callback: CallbackQuery, callback_data: AddToQueueCb) -> None:
    """Add a track from DB to the user's queue."""
    from sqlalchemy import select
    from bot.models.base import async_session
    from bot.models.track import Track

    user = await get_or_create_user(callback.from_user)
    lang = user.language

    async with async_session() as session:
        result = await session.execute(
            select(Track).where(Track.id == callback_data.tid)
        )
        track = result.scalar_one_or_none()

    if not track:
        await callback.answer("Track not found", show_alert=True)
        return

    track_dict = {
        "video_id": track.source_id,
        "title": track.title or "Unknown",
        "uploader": track.artist or "Unknown",
        "duration": track.duration or 0,
        "duration_fmt": fmt_duration(track.duration),
        "source": track.source or "youtube",
        "file_id": track.file_id,
    }
    msg = await add_to_queue(user.id, track_dict, lang)
    await callback.answer(msg, show_alert=True)
