"""
queue.py — Listening queue stored in Redis (TTL 2h, max 50 tracks).

Commands: /queue, /next
Callback buttons: ⏭ Next, 🔀 Shuffle, ❌ Clear
"""
import json
import logging
import random

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.callbacks import QueueCb, AddToQueueCb
from bot.db import get_or_create_user
from bot.i18n import t
from bot.services.cache import cache
from bot.services.track_format import audio_tag_kwargs_from_info as _audio_tag_kwargs
from bot.utils import fmt_duration

router = Router()
logger = logging.getLogger(__name__)

_MAX_QUEUE = 50
_QUEUE_TTL = 7200  # 2 hours


def _queue_key(user_id: int) -> str:
    return f"queue:{user_id}"


async def _deliver_queue_audio(msg, track: dict) -> bool:
    """Deliver a queued track: cached file_id (self-healing) or a fresh download,
    so a dead/expired file_id never silently loses the track. True if delivered."""
    from bot.services.file_id_heal import send_or_heal
    vid = track.get("video_id") or track.get("source_id") or ""
    dur = int(track["duration"]) if track.get("duration") else 0
    file_id = track.get("file_id")
    if file_id:
        sent = await send_or_heal(lambda: msg.answer_audio(
            audio=file_id, duration=dur, **_audio_tag_kwargs(track),
        ), vid, None)
        if sent is not None:
            return True
    # No usable cached file_id (missing or purged as dead) → re-download so the
    # queued track still plays and a fresh valid file_id gets cached.
    if not vid:
        return False
    try:
        import uuid as _uuid
        from aiogram.types import FSInputFile
        from aiogram.enums import ChatAction
        from bot.services.downloader import download_track, cleanup_file
        from bot.config import settings as _cfg
        try:
            await msg.bot.send_chat_action(msg.chat.id, ChatAction.UPLOAD_DOCUMENT)
        except Exception:
            pass
        # Source-aware download (mirror _group_auto_play): yandex needs download_yandex.
        if track.get("source") == "yandex" and track.get("ym_track_id"):
            from bot.services.yandex_provider import download_yandex
            mp3 = _cfg.DOWNLOAD_DIR / f"{vid}_{_uuid.uuid4().hex[:8]}.mp3"
            await download_yandex(track["ym_track_id"], mp3, 192)
        else:
            mp3 = await download_track(vid, bitrate=192, dl_id=_uuid.uuid4().hex[:8])
        sent = await msg.answer_audio(audio=FSInputFile(str(mp3)), duration=dur, **_audio_tag_kwargs(track))
        try:
            await cache.set_file_id(vid, sent.audio.file_id, 192)
        except Exception:
            pass
        cleanup_file(mp3)
        return True
    except Exception as e:
        logger.warning("queue: download fallback failed for %s: %s", vid, e)
        return False


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
        logger.debug("Failed to persist queue for user_id=%s", user_id, exc_info=True)


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
            # Do NOT call callback.answer() here — the caller (clr/next/shuf)
            # already answered the callback; a second answer raises. Render the
            # empty state by editing the message instead.
            try:
                await message_or_cb.message.edit_text(text)
            except Exception:
                await message_or_cb.message.answer(text)
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

    # Deliver (cached file_id with self-heal, else fresh download)
    if not await _deliver_queue_audio(message, track):
        # Could not play (no source to re-download) — offer search
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

        if not await _deliver_queue_audio(callback.message, track):
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
