"""
voice_chat.py — User-facing commands for Voice Chat sessions.

Commands:
  /play <query> — search and play a track in group voice chat
  /skip — skip current track
  /queue — show current queue
  /np — show now playing
"""
import logging
import secrets

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.callbacks import TrackCallback
from bot.db import get_or_create_user
from bot.i18n import t
from bot.services.cache import cache
from bot.services.downloader import search_tracks
from bot.utils import fmt_duration

logger = logging.getLogger(__name__)

router = Router()


@router.message(Command("play"))
async def cmd_play(message: Message) -> None:
    """Search and add a track to the group voice chat queue."""
    if message.chat.type not in ("group", "supergroup"):
        user = await get_or_create_user(message.from_user)
        await message.answer(t(user.language, "vc_group_only"))
        return

    user = await get_or_create_user(message.from_user)
    lang = user.language
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(t(lang, "vc_play_usage"))
        return

    query = args[1].strip()
    status_msg = await message.answer(t(lang, "searching"))

    results = await search_tracks(query, max_results=3, source="youtube")
    if not results:
        await status_msg.edit_text(t(lang, "no_results"))
        return

    from streamer.voice_chat_manager import add_to_queue, get_session, create_session

    # Ensure session exists
    session = await get_session(message.chat.id)
    if not session:
        session = await create_session(message.chat.id, message.from_user.id)

    track = results[0]
    pos = await add_to_queue(message.chat.id, track)

    await status_msg.edit_text(
        t(lang, "vc_added_to_queue",
          title=track.get("title", "?"),
          artist=track.get("uploader", "?"),
          pos=pos),
        parse_mode="HTML",
    )


@router.message(Command("skip"))
async def cmd_skip(message: Message) -> None:
    """Skip the current track in voice chat."""
    if message.chat.type not in ("group", "supergroup"):
        return

    user = await get_or_create_user(message.from_user)
    lang = user.language

    from streamer.voice_chat_manager import get_session, pop_next, update_session

    session = await get_session(message.chat.id)
    if not session:
        await message.answer(t(lang, "vc_no_session"))
        return

    next_track = await pop_next(message.chat.id)
    if next_track:
        await update_session(message.chat.id, current_track=next_track, is_playing=True)
        await message.answer(
            t(lang, "vc_skipped_to",
              title=next_track.get("title", "?"),
              artist=next_track.get("uploader", "?")),
            parse_mode="HTML",
        )
    else:
        await update_session(message.chat.id, current_track=None, is_playing=False)
        await message.answer(t(lang, "vc_queue_empty"))


@router.message(Command("queue"))
async def cmd_vc_queue(message: Message) -> None:
    """Show the current voice chat queue."""
    if message.chat.type not in ("group", "supergroup"):
        return

    user = await get_or_create_user(message.from_user)
    lang = user.language

    from streamer.voice_chat_manager import get_queue, get_now_playing

    now_playing = await get_now_playing(message.chat.id)
    queue = await get_queue(message.chat.id)

    lines = [f"<b>{t(lang, 'vc_queue_header')}</b>\n"]

    if now_playing:
        lines.append(
            f"▸ {now_playing.get('uploader', '?')} — {now_playing.get('title', '?')}"
        )
    else:
        lines.append(f"▸ {t(lang, 'vc_nothing_playing')}")

    if queue:
        lines.append(f"\n<b>{t(lang, 'vc_up_next')}:</b>")
        for i, tr in enumerate(queue[:10], 1):
            dur = fmt_duration(tr.get("duration", 0))
            lines.append(f"  {i}. {tr.get('uploader', '?')} — {tr.get('title', '?')} ({dur})")
    else:
        lines.append(f"\n{t(lang, 'vc_queue_empty')}")

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("np"))
async def cmd_now_playing(message: Message) -> None:
    """Show the currently playing track."""
    if message.chat.type not in ("group", "supergroup"):
        return

    user = await get_or_create_user(message.from_user)
    lang = user.language

    from streamer.voice_chat_manager import get_now_playing

    track = await get_now_playing(message.chat.id)
    if track:
        dur = fmt_duration(track.get("duration", 0))
        await message.answer(
            t(lang, "vc_now_playing",
              title=track.get("title", "?"),
              artist=track.get("uploader", "?"),
              duration=dur),
            parse_mode="HTML",
        )
    else:
        await message.answer(t(lang, "vc_nothing_playing"))


@router.message(Command("stop"))
async def cmd_stop_vc(message: Message) -> None:
    """Stop voice chat session and clear queue."""
    if message.chat.type not in ("group", "supergroup"):
        return

    user = await get_or_create_user(message.from_user)
    lang = user.language

    from streamer.voice_chat_manager import delete_session

    await delete_session(message.chat.id)
    await message.answer(t(lang, "vc_stopped"))
