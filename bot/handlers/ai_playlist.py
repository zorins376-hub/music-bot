"""
ai_playlist.py handler — /ai_playlist command and callback.

User sends a text prompt like "грустный плейлист на вечер" or
"energetic workout mix like Eminem" and gets a generated playlist.
"""
import secrets

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.callbacks import TrackCallback
from bot.db import get_or_create_user, record_listening_event
from bot.i18n import t
from bot.services.ai_playlist import generate_ai_playlist
from bot.services.cache import cache

router = Router()


class AiPlaylistState(StatesGroup):
    waiting_prompt = State()


@router.callback_query(lambda c: c.data == "action:ai_playlist")
async def handle_ai_playlist_btn(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language
    await callback.message.answer(
        t(lang, "ai_playlist_prompt"), parse_mode="HTML"
    )
    await state.set_state(AiPlaylistState.waiting_prompt)


@router.message(Command("ai_playlist"))
async def handle_ai_playlist_cmd(message: Message, state: FSMContext) -> None:
    user = await get_or_create_user(message.from_user)
    lang = user.language

    # If command has arguments, use them as prompt directly
    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        await _process_prompt(message, user, args[1])
        return

    await message.answer(t(lang, "ai_playlist_prompt"), parse_mode="HTML")
    await state.set_state(AiPlaylistState.waiting_prompt)


@router.message(AiPlaylistState.waiting_prompt)
async def handle_prompt_input(message: Message, state: FSMContext) -> None:
    user = await get_or_create_user(message.from_user)
    prompt = (message.text or "").strip()
    if not prompt:
        return
    await state.clear()
    await _process_prompt(message, user, prompt)


async def _process_prompt(message: Message, user, prompt: str) -> None:
    lang = user.language
    status_msg = await message.answer(
        t(lang, "ai_playlist_generating"), parse_mode="HTML"
    )

    tracks = await generate_ai_playlist(prompt, max_tracks=20, user_id=user.id)

    if not tracks:
        await status_msg.edit_text(
            t(lang, "ai_playlist_empty"), parse_mode="HTML"
        )
        return

    # Store in search cache
    session_id = secrets.token_urlsafe(6)
    await cache.store_search(session_id, tracks)
    await record_listening_event(
        user_id=user.id, action="search", source="ai_playlist"
    )

    buttons = []
    for i, tr in enumerate(tracks[:20]):
        dur = tr.get("duration_fmt", "?:??")
        label = f"♪ {tr['uploader']} — {tr['title'][:35]} ({dur})"
        buttons.append(
            [InlineKeyboardButton(
                text=label,
                callback_data=TrackCallback(sid=session_id, i=i).pack(),
            )]
        )

    # Add "Save as playlist" button
    buttons.append([
        InlineKeyboardButton(
            text="➕ " + t(lang, "ai_playlist_save_btn"),
            callback_data=f"ai_save:{session_id}",
        )
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await status_msg.edit_text(
        t(lang, "ai_playlist_header", prompt=prompt[:50]),
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data and c.data.startswith("ai_save:"))
async def handle_ai_save(callback: CallbackQuery) -> None:
    """Save AI-generated playlist as a user playlist."""
    session_id = callback.data.split(":", 1)[1]
    user = await get_or_create_user(callback.from_user)
    lang = user.language

    tracks = await cache.get_search(session_id)
    if not tracks:
        await callback.answer(t(lang, "session_expired"), show_alert=True)
        return

    from bot.models.base import async_session as db_session
    from bot.models.playlist import Playlist, PlaylistTrack
    from bot.models.track import Track
    from sqlalchemy import select

    async with db_session() as session:
        pl_name = f"AI Mix {secrets.token_hex(3)}"
        pl = Playlist(user_id=user.id, name=pl_name)
        session.add(pl)
        await session.flush()

        for i, tr in enumerate(tracks[:50]):
            existing = await session.execute(
                select(Track).where(Track.source_id == tr.get("video_id", ""))
            )
            track = existing.scalar_one_or_none()
            if not track:
                track = Track(
                    source_id=tr.get("video_id", f"ai_{i}"),
                    source=tr.get("source", "youtube"),
                    title=tr.get("title", ""),
                    artist=tr.get("uploader", ""),
                    duration=tr.get("duration"),
                )
                session.add(track)
                await session.flush()

            session.add(PlaylistTrack(
                playlist_id=pl.id, track_id=track.id, position=i,
            ))

        await session.commit()

    await callback.answer(
        t(lang, "ai_playlist_saved", name=pl_name, count=len(tracks)),
        show_alert=True,
    )
