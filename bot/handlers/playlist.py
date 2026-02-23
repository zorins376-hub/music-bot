import logging
import random as _random

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import delete, func, select

from bot.db import get_or_create_user
from bot.i18n import t
from bot.models.base import async_session
from bot.models.playlist import Playlist, PlaylistTrack
from bot.models.track import Track

logger = logging.getLogger(__name__)
router = Router()

MAX_PLAYLISTS = 20
MAX_TRACKS_PER_PLAYLIST = 50


class PlCb(CallbackData, prefix="pl"):
    """Playlist action callback."""
    act: str   # list / view / del / delcf / add / rm / play
    id: int = 0
    tid: int = 0
    p: int = 0  # page


class CreatePlaylist(StatesGroup):
    waiting_name = State()


# ── Keyboards ───────────────────────────────────────────────────────────


def _playlists_keyboard(playlists: list[Playlist], lang: str) -> InlineKeyboardMarkup:
    rows = []
    for pl in playlists:
        rows.append([InlineKeyboardButton(
            text=f"▸ {pl.name}",
            callback_data=PlCb(act="view", id=pl.id).pack(),
        )])
    rows.append([
        InlineKeyboardButton(
            text=t(lang, "pl_create_btn"),
            callback_data=PlCb(act="new").pack(),
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _playlist_view_kb(
    pl_id: int, tracks: list, lang: str, page: int = 0
) -> InlineKeyboardMarkup:
    rows = []
    # Play all / Shuffle buttons (only if there are tracks)
    if tracks:
        rows.append([
            InlineKeyboardButton(
                text=t(lang, "pl_play_all"),
                callback_data=PlCb(act="pall", id=pl_id).pack(),
            ),
            InlineKeyboardButton(
                text=t(lang, "pl_shuffle"),
                callback_data=PlCb(act="shuf", id=pl_id).pack(),
            ),
        ])
    start = page * 10
    for i, (pt, tr) in enumerate(tracks[start : start + 10], start=start):
        dur = f"{tr.duration // 60}:{tr.duration % 60:02d}" if tr.duration else "?:??"
        label = f"▸ {i + 1}. {tr.artist or '?'} — {(tr.title or '?')[:28]} ({dur})"
        rows.append([
            InlineKeyboardButton(
                text=label,
                callback_data=PlCb(act="play", id=pl_id, tid=tr.id).pack(),
            ),
            InlineKeyboardButton(
                text="✕",
                callback_data=PlCb(act="rm", id=pl_id, tid=pt.id).pack(),
            ),
        ])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text="◁", callback_data=PlCb(act="view", id=pl_id, p=page - 1).pack(),
        ))
    if start + 10 < len(tracks):
        nav.append(InlineKeyboardButton(
            text="▷", callback_data=PlCb(act="view", id=pl_id, p=page + 1).pack(),
        ))
    if nav:
        rows.append(nav)
    rows.append([
        InlineKeyboardButton(
            text=t(lang, "pl_delete_btn"),
            callback_data=PlCb(act="del", id=pl_id).pack(),
        ),
        InlineKeyboardButton(
            text=t(lang, "pl_back_btn"),
            callback_data=PlCb(act="list").pack(),
        ),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── /playlist command ────────────────────────────────────────────────────


@router.message(Command("playlist"))
async def cmd_playlist(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    await _show_playlists(message, user.id, user.language, edit=False)


@router.callback_query(lambda c: c.data == "action:playlist")
async def cb_playlist(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    await _show_playlists(callback.message, user.id, user.language, edit=True)


async def _show_playlists(
    msg: Message, user_id: int, lang: str, edit: bool = False
) -> None:
    async with async_session() as session:
        result = await session.execute(
            select(Playlist)
            .where(Playlist.user_id == user_id)
            .order_by(Playlist.created_at)
        )
        pls = list(result.scalars().all())

    text = t(lang, "pl_header", count=len(pls), max=MAX_PLAYLISTS)
    kb = _playlists_keyboard(pls, lang)
    if edit:
        await msg.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await msg.answer(text, reply_markup=kb, parse_mode="HTML")


# ── Create playlist ─────────────────────────────────────────────────────


@router.callback_query(PlCb.filter(F.act == "new"))
async def cb_create_start(callback: CallbackQuery, state: FSMContext) -> None:
    user = await get_or_create_user(callback.from_user)
    async with async_session() as session:
        cnt = await session.scalar(
            select(func.count()).where(Playlist.user_id == user.id)
        )
    if cnt >= MAX_PLAYLISTS:
        await callback.answer(t(user.language, "pl_limit"), show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(t(user.language, "pl_enter_name"))
    await state.set_state(CreatePlaylist.waiting_name)


@router.message(CreatePlaylist.waiting_name)
async def create_playlist_name(message: Message, state: FSMContext) -> None:
    user = await get_or_create_user(message.from_user)
    name = message.text.strip()[:100] if message.text else ""
    if not name:
        await message.answer(t(user.language, "pl_enter_name"))
        return
    async with async_session() as session:
        pl = Playlist(user_id=user.id, name=name)
        session.add(pl)
        await session.commit()
    await state.clear()
    await message.answer(
        t(user.language, "pl_created", name=name),
        parse_mode="HTML",
    )
    await _show_playlists(message, user.id, user.language, edit=False)


# ── View playlist ───────────────────────────────────────────────────────


@router.callback_query(PlCb.filter(F.act == "view"))
async def cb_view(callback: CallbackQuery, callback_data: PlCb) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    async with async_session() as session:
        pl = await session.get(Playlist, callback_data.id)
        if not pl or pl.user_id != user.id:
            await callback.message.edit_text(t(user.language, "pl_not_found"))
            return
        result = await session.execute(
            select(PlaylistTrack, Track)
            .join(Track, PlaylistTrack.track_id == Track.id)
            .where(PlaylistTrack.playlist_id == pl.id)
            .order_by(PlaylistTrack.position)
        )
        tracks = list(result.all())

    text = t(user.language, "pl_view", name=pl.name, count=len(tracks), max=MAX_TRACKS_PER_PLAYLIST)
    kb = _playlist_view_kb(pl.id, tracks, user.language, page=callback_data.p)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(PlCb.filter(F.act == "list"))
async def cb_back_to_list(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    await _show_playlists(callback.message, user.id, user.language, edit=True)


# ── Delete playlist ─────────────────────────────────────────────────────


@router.callback_query(PlCb.filter(F.act == "del"))
async def cb_delete_confirm(callback: CallbackQuery, callback_data: PlCb) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text=t(user.language, "pl_confirm_yes"),
            callback_data=PlCb(act="delcf", id=callback_data.id).pack(),
        ),
        InlineKeyboardButton(
            text=t(user.language, "pl_confirm_no"),
            callback_data=PlCb(act="view", id=callback_data.id).pack(),
        ),
    ]])
    await callback.message.edit_text(
        t(user.language, "pl_delete_confirm"), reply_markup=kb
    )


@router.callback_query(PlCb.filter(F.act == "delcf"))
async def cb_delete_exec(callback: CallbackQuery, callback_data: PlCb) -> None:
    user = await get_or_create_user(callback.from_user)
    async with async_session() as session:
        pl = await session.get(Playlist, callback_data.id)
        if not pl or pl.user_id != user.id:
            await callback.answer(t(user.language, "pl_not_found"), show_alert=True)
            return
        await session.execute(
            delete(PlaylistTrack).where(PlaylistTrack.playlist_id == pl.id)
        )
        await session.delete(pl)
        await session.commit()
    await callback.answer(t(user.language, "pl_deleted"))
    await _show_playlists(callback.message, user.id, user.language, edit=True)


# ── Remove track from playlist ──────────────────────────────────────────


@router.callback_query(PlCb.filter(F.act == "rm"))
async def cb_remove_track(callback: CallbackQuery, callback_data: PlCb) -> None:
    user = await get_or_create_user(callback.from_user)
    async with async_session() as session:
        pt = await session.get(PlaylistTrack, callback_data.tid)
        if pt:
            pl = await session.get(Playlist, pt.playlist_id)
            if pl and pl.user_id == user.id:
                await session.delete(pt)
                await session.commit()
    await callback.answer(t(user.language, "pl_track_removed"))
    # Refresh view
    cb2 = PlCb(act="view", id=callback_data.id)
    await cb_view(callback, cb2)


# ── Play single track from playlist ─────────────────────────────────────


@router.callback_query(PlCb.filter(F.act == "play"))
async def cb_play_track(callback: CallbackQuery, callback_data: PlCb) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    async with async_session() as session:
        tr = await session.get(Track, callback_data.tid)
        if not tr or not tr.file_id:
            await callback.message.answer(t(user.language, "pl_track_no_file"))
            return
    dur = f"{tr.duration // 60}:{tr.duration % 60:02d}" if tr.duration else ""
    caption = f"{tr.artist or '?'} — {tr.title or '?'}"
    if dur:
        caption += f" ({dur})"
    await callback.message.answer_audio(
        audio=tr.file_id,
        title=tr.title,
        performer=tr.artist,
        duration=tr.duration,
        caption=caption,
    )


# ── Play all / Shuffle ──────────────────────────────────────────────────


async def _send_playlist_tracks(callback: CallbackQuery, pl_id: int, shuffle: bool) -> None:
    user = await get_or_create_user(callback.from_user)
    async with async_session() as session:
        pl = await session.get(Playlist, pl_id)
        if not pl or pl.user_id != user.id:
            await callback.message.answer(t(user.language, "pl_not_found"))
            return
        result = await session.execute(
            select(Track)
            .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)
            .where(PlaylistTrack.playlist_id == pl.id)
            .order_by(PlaylistTrack.position)
        )
        tracks = list(result.scalars().all())

    playable = [tr for tr in tracks if tr.file_id]
    if not playable:
        await callback.message.answer(t(user.language, "pl_no_playable"))
        return

    if shuffle:
        _random.shuffle(playable)

    mode = t(user.language, "pl_shuffle") if shuffle else t(user.language, "pl_play_all")
    await callback.message.answer(
        t(user.language, "pl_playing", name=pl.name, mode=mode, count=len(playable)),
        parse_mode="HTML",
    )

    for tr in playable:
        try:
            await callback.message.answer_audio(
                audio=tr.file_id,
                title=tr.title,
                performer=tr.artist,
                duration=tr.duration,
            )
        except Exception:
            logger.warning("Failed to send track %s from playlist %s", tr.id, pl_id)


@router.callback_query(PlCb.filter(F.act == "pall"))
async def cb_play_all(callback: CallbackQuery, callback_data: PlCb) -> None:
    await callback.answer()
    await _send_playlist_tracks(callback, callback_data.id, shuffle=False)


@router.callback_query(PlCb.filter(F.act == "shuf"))
async def cb_shuffle(callback: CallbackQuery, callback_data: PlCb) -> None:
    await callback.answer()
    await _send_playlist_tracks(callback, callback_data.id, shuffle=True)


# ── Add track to playlist (called from search after download) ────────────


class AddToPlCb(CallbackData, prefix="apl"):
    """Add to playlist callback."""
    tid: int   # track DB id
    pid: int = 0   # playlist id (0 = pick playlist)


@router.callback_query(AddToPlCb.filter(F.pid == 0))
async def cb_pick_playlist(callback: CallbackQuery, callback_data: AddToPlCb) -> None:
    """Show user's playlists to pick which one to add to."""
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    async with async_session() as session:
        result = await session.execute(
            select(Playlist)
            .where(Playlist.user_id == user.id)
            .order_by(Playlist.created_at)
        )
        pls = list(result.scalars().all())

    if not pls:
        await callback.message.answer(t(user.language, "pl_empty_create_first"))
        return

    rows = []
    for pl in pls:
        rows.append([InlineKeyboardButton(
            text=f"▸ {pl.name}",
            callback_data=AddToPlCb(tid=callback_data.tid, pid=pl.id).pack(),
        )])
    await callback.message.answer(
        t(user.language, "pl_pick"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(AddToPlCb.filter(F.pid > 0))
async def cb_add_to_playlist(callback: CallbackQuery, callback_data: AddToPlCb) -> None:
    user = await get_or_create_user(callback.from_user)
    async with async_session() as session:
        pl = await session.get(Playlist, callback_data.pid)
        if not pl or pl.user_id != user.id:
            await callback.answer(t(user.language, "pl_not_found"), show_alert=True)
            return
        # Check limit
        cnt = await session.scalar(
            select(func.count()).where(PlaylistTrack.playlist_id == pl.id)
        )
        if cnt >= MAX_TRACKS_PER_PLAYLIST:
            await callback.answer(t(user.language, "pl_track_limit"), show_alert=True)
            return
        # Check duplicate
        existing = await session.scalar(
            select(func.count()).where(
                PlaylistTrack.playlist_id == pl.id,
                PlaylistTrack.track_id == callback_data.tid,
            )
        )
        if existing:
            await callback.answer(t(user.language, "pl_track_exists"), show_alert=True)
            return
        pt = PlaylistTrack(
            playlist_id=pl.id,
            track_id=callback_data.tid,
            position=cnt,
        )
        session.add(pt)
        await session.commit()
    await callback.answer(t(user.language, "pl_track_added", name=pl.name), show_alert=True)
    await callback.message.delete()
