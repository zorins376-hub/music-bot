"""
import_playlist.py handler — Import playlists from Spotify / Yandex Music.

User sends /import or clicks button, then pastes a playlist URL.
Bot fetches track list, searches each track, creates a Playlist.
"""
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from bot.db import get_or_create_user
from bot.i18n import t
from bot.models.base import async_session
from bot.models.playlist import Playlist, PlaylistTrack
from bot.models.track import Track
from bot.services.playlist_import import detect_playlist_url, import_playlist_tracks

logger = logging.getLogger(__name__)
router = Router()

MAX_PLAYLISTS = 20


class ImportState(StatesGroup):
    waiting_url = State()


@router.callback_query(lambda c: c.data == "action:import_playlist")
async def handle_import_btn(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    await callback.message.answer(
        t(user.language, "import_prompt"), parse_mode="HTML"
    )
    await state.set_state(ImportState.waiting_url)


@router.message(Command("import_playlist"))
async def handle_import_cmd(message: Message, state: FSMContext) -> None:
    user = await get_or_create_user(message.from_user)
    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        await _process_import(message, user, args[1].strip())
        return
    await message.answer(t(user.language, "import_prompt"), parse_mode="HTML")
    await state.set_state(ImportState.waiting_url)


@router.message(ImportState.waiting_url)
async def handle_url_input(message: Message, state: FSMContext) -> None:
    user = await get_or_create_user(message.from_user)
    url = (message.text or "").strip()
    if not url:
        return
    await state.clear()
    await _process_import(message, user, url)


async def _process_import(message: Message, user, url: str) -> None:
    lang = user.language

    source = detect_playlist_url(url)
    if not source:
        await message.answer(t(lang, "import_invalid_url"), parse_mode="HTML")
        return

    # Check playlist limit
    async with async_session() as session:
        result = await session.execute(
            select(func.count(Playlist.id)).where(Playlist.user_id == user.id)
        )
        count = result.scalar() or 0
        if count >= MAX_PLAYLISTS:
            await message.answer(t(lang, "pl_limit"), parse_mode="HTML")
            return

    status_msg = await message.answer(
        t(lang, "import_detecting"), parse_mode="HTML"
    )

    # Progress callback to update status message
    _last_update = [0]

    async def _progress(found: int, total: int):
        # Update every 5 tracks to avoid flood
        if found - _last_update[0] >= 5 or found == total:
            _last_update[0] = found
            try:
                await status_msg.edit_text(
                    t(lang, "import_progress", found=found, total=total),
                    parse_mode="HTML",
                )
            except Exception:
                pass

    name, found_tracks, total = await import_playlist_tracks(url, source, progress_cb=_progress)

    if not found_tracks:
        await status_msg.edit_text(
            t(lang, "import_empty"), parse_mode="HTML"
        )
        return

    # Create playlist and add found tracks
    async with async_session() as session:
        pl = Playlist(user_id=user.id, name=name[:100])
        session.add(pl)
        await session.flush()

        for i, tr in enumerate(found_tracks[:50]):
            # Find or create track in DB
            existing = await session.execute(
                select(Track).where(Track.source_id == tr.get("video_id", ""))
            )
            track = existing.scalar_one_or_none()

            if not track:
                track = Track(
                    source_id=tr.get("video_id", f"import_{i}"),
                    source=tr.get("source", "youtube"),
                    title=tr.get("title", ""),
                    artist=tr.get("uploader", ""),
                    duration=tr.get("duration"),
                )
                session.add(track)
                await session.flush()

            pt = PlaylistTrack(
                playlist_id=pl.id,
                track_id=track.id,
                position=i,
            )
            session.add(pt)

        await session.commit()

    await status_msg.edit_text(
        t(lang, "import_done", name=name[:50], found=len(found_tracks), total=total),
        parse_mode="HTML",
    )
