import io
import json as _json
import logging
import random as _random
import secrets
import uuid

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import delete, func, select, update

from bot.config import settings
from bot.db import get_or_create_user
from bot.i18n import t
from bot.models.base import async_session
from bot.models.playlist import Playlist, PlaylistTrack
from bot.models.track import Track
from bot.services.share_links import create_share_link, resolve_share_link
from bot.callbacks import AddToPlCb
from bot.services.cache import cache
from bot.services.downloader import cleanup_file, download_track

logger = logging.getLogger(__name__)
router = Router()

MAX_PLAYLISTS = 20
MAX_TRACKS_PER_PLAYLIST = 50


from aiogram.filters.callback_data import CallbackData

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
            text="📤 Export",
            callback_data=PlCb(act="exp", id=pl_id).pack(),
        ),
        InlineKeyboardButton(
            text="🔗",
            callback_data=PlCb(act="shr", id=pl_id).pack(),
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
    text = (message.text or "").strip()
    parts = text.split(maxsplit=2)
    if len(parts) >= 2 and parts[1].lower() == "export":
        if len(parts) < 3 or not parts[2].strip():
            await message.answer(t(user.language, "pl_export_usage"))
            return
        await _export_playlist_by_name(message, user.id, user.language, parts[2].strip())
        return
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
        await session.refresh(pl)
        # Mirror to Supabase
        try:
            from bot.services.supabase_mirror import mirror_playlist_create
            mirror_playlist_create(pl.id, user.id, name)
        except Exception:
            logger.debug("mirror_playlist_create failed pl=%s", pl.id, exc_info=True)
    await state.clear()
    try:
        from bot.services.achievements import check_and_award_badges
        await check_and_award_badges(user.id, "playlist_create")
    except Exception:
        logger.debug("check_and_award_badges failed user=%s", user.id, exc_info=True)
    try:
        from bot.services.leaderboard import add_xp, XP_PLAYLIST_CREATE
        await add_xp(user.id, XP_PLAYLIST_CREATE)
    except Exception:
        logger.debug("add_xp failed user=%s", user.id, exc_info=True)
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
        # Mirror to Supabase
        try:
            from bot.services.supabase_mirror import mirror_playlist_delete
            mirror_playlist_delete(pl.id)
        except Exception:
            logger.debug("mirror_playlist_delete failed pl=%s", pl.id, exc_info=True)
    await callback.answer(t(user.language, "pl_deleted"))
    await _show_playlists(callback.message, user.id, user.language, edit=True)


# ── Remove track from playlist ──────────────────────────────────────────


@router.callback_query(PlCb.filter(F.act == "rm"))
async def cb_remove_track(callback: CallbackQuery, callback_data: PlCb) -> None:
    user = await get_or_create_user(callback.from_user)
    playlist_id = callback_data.id  # fallback
    async with async_session() as session:
        pt = await session.get(PlaylistTrack, callback_data.tid)
        if pt:
            playlist_id = pt.playlist_id
            pl = await session.get(Playlist, pt.playlist_id)
            if pl and pl.user_id == user.id:
                pt_id = pt.id
                await session.delete(pt)
                await session.commit()
                # Mirror to Supabase
                try:
                    from bot.services.supabase_mirror import mirror_playlist_track_remove
                    mirror_playlist_track_remove(pt_id)
                except Exception:
                    logger.debug("mirror_playlist_track_remove failed pt=%s", pt_id, exc_info=True)
    await callback.answer(t(user.language, "pl_track_removed"))
    # Refresh view using server-side playlist_id
    cb2 = PlCb(act="view", id=playlist_id)
    await cb_view(callback, cb2)


# ── Play single track from playlist ─────────────────────────────────────


async def _send_playlist_track_audio(message: Message, user, track: Track) -> bool:
    """Send track audio using file_id, cache fallback, or lazy download.

    Returns True if track was sent, False otherwise.
    """
    # 1) Direct DB file_id
    if track.file_id:
        await message.answer_audio(
            audio=track.file_id,
            title=track.title,
            performer=track.artist,
            duration=track.duration,
        )
        return True

    # 2) Try file_id cache by common bitrates
    for br in (192, 320, 128):
        fid = await cache.get_file_id(track.source_id, br)
        if fid:
            try:
                await message.answer_audio(
                    audio=fid,
                    title=track.title,
                    performer=track.artist,
                    duration=track.duration,
                )
                async with async_session() as session:
                    await session.execute(
                        update(Track).where(Track.id == track.id).values(file_id=fid)
                    )
                    await session.commit()
                return True
            except Exception:
                continue

    # 3) Lazy download (for youtube-like source_id), then send and persist file_id
    source_id = (track.source_id or "").strip()
    if not source_id:
        return False

    bitrate = int(user.quality) if str(user.quality).isdigit() else 192
    if not user.is_premium:
        bitrate = min(bitrate, 192)

    mp3_path = None
    try:
        mp3_path = await download_track(source_id, bitrate=bitrate, dl_id=uuid.uuid4().hex[:8])
        sent = await message.answer_audio(
            audio=FSInputFile(mp3_path),
            title=track.title,
            performer=track.artist,
            duration=track.duration,
        )
        fid = sent.audio.file_id if sent and sent.audio else None
        if fid:
            try:
                await cache.set_file_id(source_id, fid, bitrate)
            except Exception:
                logger.debug("cache.set_file_id failed source=%s", source_id, exc_info=True)
            async with async_session() as session:
                await session.execute(
                    update(Track).where(Track.id == track.id).values(file_id=fid)
                )
                await session.commit()
        return True
    except Exception as e:
        logger.warning("Playlist lazy download failed for track %s (%s): %s", track.id, source_id, e)
        return False
    finally:
        if mp3_path:
            cleanup_file(mp3_path)


@router.callback_query(PlCb.filter(F.act == "play"))
async def cb_play_track(callback: CallbackQuery, callback_data: PlCb) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    async with async_session() as session:
        tr = await session.get(Track, callback_data.tid)
        if not tr:
            await callback.message.answer(t(user.language, "pl_track_no_file"))
            return
    sent_ok = await _send_playlist_track_audio(callback.message, user, tr)
    if not sent_ok:
        await callback.message.answer(t(user.language, "pl_track_no_file"))


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

    play_order = list(tracks)
    if shuffle:
        _random.shuffle(play_order)

    mode = t(user.language, "pl_shuffle") if shuffle else t(user.language, "pl_play_all")
    await callback.message.answer(
        t(user.language, "pl_playing", name=pl.name, mode=mode, count=len(play_order)),
        parse_mode="HTML",
    )

    sent_count = 0
    for tr in play_order:
        try:
            ok = await _send_playlist_track_audio(callback.message, user, tr)
            if ok:
                sent_count += 1
        except Exception:
            logger.warning("Failed to send track %s from playlist %s", tr.id, pl_id)

    if sent_count == 0:
        await callback.message.answer(t(user.language, "pl_no_playable"))


@router.callback_query(PlCb.filter(F.act == "pall"))
async def cb_play_all(callback: CallbackQuery, callback_data: PlCb) -> None:
    await callback.answer()
    await _send_playlist_tracks(callback, callback_data.id, shuffle=False)


@router.callback_query(PlCb.filter(F.act == "shuf"))
async def cb_shuffle(callback: CallbackQuery, callback_data: PlCb) -> None:
    await callback.answer()
    await _send_playlist_tracks(callback, callback_data.id, shuffle=True)


# ── Export playlist (TASK-017) ───────────────────────────────────────────


@router.callback_query(PlCb.filter(F.act == "exp"))
async def cb_export(callback: CallbackQuery, callback_data: PlCb) -> None:
    """Export playlist as TXT file."""
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    async with async_session() as session:
        pl = await session.get(Playlist, callback_data.id)
        if not pl or pl.user_id != user.id:
            await callback.message.answer(t(user.language, "pl_not_found"))
            return
        tracks = await _get_playlist_tracks(session, pl.id)

    await _send_playlist_export(callback.message, user.language, pl, tracks)


async def _get_playlist_tracks(session, playlist_id: int) -> list[Track]:
    result = await session.execute(
        select(Track)
        .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)
        .where(PlaylistTrack.playlist_id == playlist_id)
        .order_by(PlaylistTrack.position)
    )
    return list(result.scalars().all())


async def _send_playlist_export(message: Message, lang: str, pl: Playlist, tracks: list[Track]) -> None:
    if not tracks:
        await message.answer(t(lang, "pl_empty"))
        return

    lines = [f"# {pl.name}\n"]
    for i, tr in enumerate(tracks, 1):
        dur = f"{tr.duration // 60}:{tr.duration % 60:02d}" if tr.duration else "?:??"
        lines.append(f"{i}. {tr.artist or '?'} - {tr.title or '?'} ({dur})")

    txt_content = "\n".join(lines).encode("utf-8")
    safe_name = pl.name.replace(" ", "_")[:30]
    await message.answer_document(
        document=BufferedInputFile(txt_content, filename=f"playlist_{safe_name}.txt"),
        caption=t(lang, "pl_export_caption", name=pl.name, count=len(tracks)),
    )


async def _export_playlist_by_name(message: Message, user_id: int, lang: str, playlist_name: str) -> None:
    async with async_session() as session:
        pl = await session.scalar(
            select(Playlist)
            .where(
                Playlist.user_id == user_id,
                func.lower(Playlist.name) == playlist_name.lower(),
            )
        )
        if not pl:
            await message.answer(t(lang, "pl_not_found"))
            return
        tracks = await _get_playlist_tracks(session, pl.id)

    await _send_playlist_export(message, lang, pl, tracks)


# ── Add track to playlist (called from search after download) ────────────

# AddToPlCb imported from bot.callbacks


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
        await session.refresh(pt)
        # Mirror to Supabase
        try:
            from bot.services.supabase_mirror import mirror_playlist_track_add
            mirror_playlist_track_add(pt.id, pl.id, callback_data.tid, cnt)
        except Exception:
            logger.debug("mirror_playlist_track_add failed pt=%s", pt.id, exc_info=True)
    await callback.answer(t(user.language, "pl_track_added", name=pl.name), show_alert=True)
    await callback.message.delete()


# ── Share playlist (C-04) ────────────────────────────────────────────────

_SHARE_TTL = 30 * 24 * 3600  # 30 days


@router.callback_query(PlCb.filter(F.act == "shr"))
async def cb_share_playlist(callback: CallbackQuery, callback_data: PlCb) -> None:
    """Generate a shareable deep-link for a playlist."""
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    async with async_session() as session:
        pl = await session.get(Playlist, callback_data.id)
        if not pl or pl.user_id != user.id:
            await callback.message.answer(t(user.language, "pl_not_found"))
            return

    try:
        share_id = await create_share_link(
            owner_id=user.id,
            entity_type="playlist",
            entity_id=pl.id,
            ttl_seconds=_SHARE_TTL,
        )
    except Exception:
        await callback.message.answer("⚠️ Не удалось создать ссылку.")
        return

    bot_me = await callback.bot.me()
    link = f"https://t.me/{bot_me.username}?start=pl_{share_id}"
    await callback.message.answer(
        f"🔗 <b>Ссылка на плейлист «{pl.name}»</b>\n\n"
        f"<code>{link}</code>\n\n"
        f"Отправь эту ссылку друзьям — они смогут посмотреть и скопировать плейлист!",
        parse_mode="HTML",
    )


async def show_shared_playlist(message: Message, share_id: str) -> None:
    """Display a shared playlist to the recipient (called from start.py deep-link)."""
    user = await get_or_create_user(message.from_user)
    lang = user.language

    data = await resolve_share_link(share_id)
    if not data or data.get("entity_type") != "playlist":
        await message.answer(t(lang, "pl_share_expired"))
        return

    playlist_id = int(data.get("entity_id") or 0)

    async with async_session() as session:
        pl = await session.get(Playlist, playlist_id)
        if not pl:
            await message.answer(t(lang, "pl_not_found"))
            return

        result = await session.execute(
            select(Track)
            .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)
            .where(PlaylistTrack.playlist_id == pl.id)
            .order_by(PlaylistTrack.position)
        )
        tracks = list(result.scalars().all())

    if not tracks:
        await message.answer(t(lang, "pl_empty"))
        return

    lines = [f"▸ <b>{pl.name}</b> ({len(tracks)} треков)\n"]
    for i, tr in enumerate(tracks[:20], 1):
        dur = f"{tr.duration // 60}:{tr.duration % 60:02d}" if tr.duration else "?:??"
        lines.append(f"{i}. {tr.artist or '?'} — {tr.title or '?'} ({dur})")
    if len(tracks) > 20:
        lines.append(f"... ещё {len(tracks) - 20} треков")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📥 Скопировать к себе",
            callback_data=PlCb(act="clone", id=playlist_id).pack(),
        )],
    ])
    await message.answer("\n".join(lines), reply_markup=kb, parse_mode="HTML")


@router.callback_query(PlCb.filter(F.act == "clone"))
async def cb_clone_playlist(callback: CallbackQuery, callback_data: PlCb) -> None:
    """Clone a shared playlist to the current user."""
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language

    async with async_session() as session:
        # Check user playlist limit
        cnt = await session.scalar(
            select(func.count()).where(Playlist.user_id == user.id)
        )
        if cnt >= MAX_PLAYLISTS:
            await callback.message.answer(t(lang, "pl_limit"))
            return

        # Get source playlist
        src = await session.get(Playlist, callback_data.id)
        if not src:
            await callback.message.answer(t(lang, "pl_not_found"))
            return

        # Get source tracks
        result = await session.execute(
            select(PlaylistTrack)
            .where(PlaylistTrack.playlist_id == src.id)
            .order_by(PlaylistTrack.position)
        )
        src_tracks = list(result.scalars().all())

        # Create new playlist
        new_pl = Playlist(user_id=user.id, name=src.name)
        session.add(new_pl)
        await session.flush()

        for pt in src_tracks:
            session.add(PlaylistTrack(
                playlist_id=new_pl.id,
                track_id=pt.track_id,
                position=pt.position,
            ))
        await session.commit()

    await callback.message.answer(
        t(lang, "pl_cloned", name=src.name, count=len(src_tracks)),
    )


# ── Import playlist from JSON file (C-05) ───────────────────────────────


@router.message(F.document)
async def handle_playlist_import(message: Message) -> None:
    """Import a playlist from a JSON file sent by the user."""
    doc = message.document
    if not doc or not doc.file_name:
        return
    if not doc.file_name.endswith(".json"):
        return
    if doc.file_size and doc.file_size > 512 * 1024:  # 512 KB max
        return

    user = await get_or_create_user(message.from_user)
    lang = user.language

    try:
        file = await message.bot.download(doc)
        raw = file.read()
        data = _json.loads(raw)
    except Exception:
        await message.answer(t(lang, "pl_import_error"))
        return

    name = data.get("name", "Imported")[:50]
    tracks_data = data.get("tracks", [])
    if not tracks_data or not isinstance(tracks_data, list):
        await message.answer(t(lang, "pl_import_error"))
        return

    async with async_session() as session:
        cnt = await session.scalar(
            select(func.count()).where(Playlist.user_id == user.id)
        )
        if cnt >= MAX_PLAYLISTS:
            await message.answer(t(lang, "pl_limit"))
            return

        pl = Playlist(user_id=user.id, name=name)
        session.add(pl)
        await session.flush()

        added = 0
        for i, item in enumerate(tracks_data[:MAX_TRACKS_PER_PLAYLIST]):
            artist = item.get("artist", "").strip()
            title = item.get("title", "").strip()
            source_id = item.get("source_id", "").strip()
            if not title:
                continue
            # Find or skip the track in local DB
            track = await session.scalar(
                select(Track).where(Track.source_id == source_id)
            ) if source_id else None
            if not track:
                track = await session.scalar(
                    select(Track).where(
                        Track.artist.ilike(f"%{artist}%"),
                        Track.title.ilike(f"%{title}%"),
                    )
                ) if artist and title else None
            if track:
                session.add(PlaylistTrack(
                    playlist_id=pl.id,
                    track_id=track.id,
                    position=added,
                ))
                added += 1

        await session.commit()

    await message.answer(t(lang, "pl_imported", name=name, count=added))
