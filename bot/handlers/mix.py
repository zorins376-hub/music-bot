from datetime import datetime, timezone
import secrets

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from bot.callbacks import MixCb, TrackCallback
from bot.db import get_or_create_user
from bot.i18n import t
from bot.models.base import async_session
from bot.models.playlist import Playlist, PlaylistTrack
from bot.models.track import Track
from bot.services.cache import cache
from bot.services.daily_mix import get_or_build_daily_mix

router = Router()

MAX_PLAYLISTS = 20
MAX_TRACKS_PER_PLAYLIST = 50


def _mix_keyboard(session_id: str, tracks: list[dict], lang: str) -> InlineKeyboardMarkup:
    rows = []
    for i, tr in enumerate(tracks[:10]):
        label = f"♪ {(tr.get('uploader') or '?')[:22]} — {(tr.get('title') or '?')[:24]} ({tr.get('duration_fmt', '?:??')})"
        rows.append([
            InlineKeyboardButton(
                text=label,
                callback_data=TrackCallback(sid=session_id, i=i).pack(),
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text=t(lang, "mix_save_btn"),
            callback_data=MixCb(act="save", sid=session_id).pack(),
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_daily_mix(message: Message, user_id: int, lang: str) -> None:
    tracks = await get_or_build_daily_mix(user_id, limit=25)
    if not tracks:
        await message.answer(t(lang, "mix_empty"))
        return

    session_id = secrets.token_urlsafe(6)
    await cache.store_search(session_id, tracks)

    await message.answer(
        t(lang, "mix_header", count=len(tracks)),
        reply_markup=_mix_keyboard(session_id, tracks, lang),
        parse_mode="HTML",
    )


@router.message(Command("mix"))
async def cmd_mix(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    await send_daily_mix(message, user.id, user.language)


@router.callback_query(lambda c: c.data == "action:mix")
async def cb_mix(callback: CallbackQuery) -> None:
    user = await get_or_create_user(callback.from_user)
    await callback.answer()
    await send_daily_mix(callback.message, user.id, user.language)


@router.callback_query(MixCb.filter())
async def cb_mix_action(callback: CallbackQuery, callback_data: MixCb) -> None:
    user = await get_or_create_user(callback.from_user)
    lang = user.language

    if callback_data.act != "save":
        await callback.answer()
        return

    tracks = await cache.get_search(callback_data.sid)
    if not tracks:
        await callback.answer(t(lang, "mix_expired"), show_alert=True)
        return

    playlist_name = t(
        lang,
        "mix_playlist_name",
        date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )

    async with async_session() as session:
        cnt = await session.scalar(
            select(func.count()).where(Playlist.user_id == user.id)
        )
        if cnt >= MAX_PLAYLISTS:
            await callback.answer(t(lang, "pl_limit"), show_alert=True)
            return

        existing = await session.execute(
            select(Playlist).where(Playlist.user_id == user.id, Playlist.name == playlist_name)
        )
        pl = existing.scalar_one_or_none()
        if pl is None:
            pl = Playlist(user_id=user.id, name=playlist_name)
            session.add(pl)
            await session.flush()

        source_ids = [str(tr.get("video_id", "")).strip() for tr in tracks if tr.get("video_id")]
        existing_tracks_r = await session.execute(
            select(Track).where(Track.source_id.in_(source_ids))
        ) if source_ids else None
        by_source = {tr.source_id: tr for tr in (existing_tracks_r.scalars().all() if existing_tracks_r else [])}

        existing_pt_r = await session.execute(
            select(PlaylistTrack.track_id).where(PlaylistTrack.playlist_id == pl.id)
        )
        in_playlist = {row[0] for row in existing_pt_r.all()}

        pos_r = await session.execute(
            select(func.count()).where(PlaylistTrack.playlist_id == pl.id)
        )
        pos = int(pos_r.scalar() or 0)
        added = 0

        for tr in tracks:
            if pos >= MAX_TRACKS_PER_PLAYLIST:
                break
            source_id = str(tr.get("video_id", "")).strip()
            if not source_id:
                continue

            db_track = by_source.get(source_id)
            if db_track is None:
                db_track = Track(
                    source_id=source_id,
                    title=tr.get("title"),
                    artist=tr.get("uploader"),
                    duration=int(tr["duration"]) if tr.get("duration") else None,
                    source=tr.get("source", "youtube"),
                    channel="external",
                    downloads=0,
                )
                session.add(db_track)
                await session.flush()
                by_source[source_id] = db_track

            if db_track.id in in_playlist:
                continue

            session.add(
                PlaylistTrack(
                    playlist_id=pl.id,
                    track_id=db_track.id,
                    position=pos,
                )
            )
            in_playlist.add(db_track.id)
            pos += 1
            added += 1

        await session.commit()

    await callback.answer(t(lang, "mix_saved", count=added), show_alert=True)
