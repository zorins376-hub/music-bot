import asyncio
import json
import logging
import random as _random
from pathlib import Path

from aiogram import F, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select, distinct
from sqlalchemy.sql import func

from bot.db import get_or_create_user, upsert_track
from bot.i18n import t
from bot.models.base import async_session
from bot.models.track import Track
from bot.services.cache import cache
from bot.services.downloader import download_track
from bot.config import settings

logger = logging.getLogger(__name__)

router = Router()

# Ключи в Redis, которые стример (v1.1) будет обновлять
_CURRENT_TRACK_KEY = "radio:current:{channel}"  # channel: tequila / fullmoon

# Fallback genre list (shown if DB has no genre data)
_DEFAULT_GENRES = [
    "Hip-Hop", "Pop", "R&B", "Electronic", "Rock",
    "Jazz", "Lo-fi", "Trap", "House", "Reggaeton",
]


class MixCb(CallbackData, prefix="mix"):
    act: str       # genre / go
    genre: str = ""


async def _get_current_track(channel: str) -> dict | None:
    """Возвращает текущий трек из Redis (заполняется стримером в v1.1)."""
    import json
    data = await cache.redis.get(_CURRENT_TRACK_KEY.format(channel=channel))
    return json.loads(data) if data else None


class LiveCb(CallbackData, prefix="live"):
    act: str       # play / next / shuf
    ch: str        # tequila / fullmoon


_LIVE_BATCH = 5  # tracks per "page"


async def _send_live_menu(message, lang: str, channel: str) -> None:
    """Show live channel menu with track count + play buttons."""
    label = "TEQUILA" if channel == "tequila" else "FULLMOON"
    icon = "●" if channel == "tequila" else "◑"

    # Check if there's a live stream
    track = await _get_current_track(channel)

    async with async_session() as session:
        count = await session.scalar(
            select(func.count()).select_from(Track).where(Track.channel == channel)
        ) or 0

    if track:
        text = (
            f"{icon} <b>{label} LIVE</b>\n\n"
            f"▸ Сейчас играет:\n"
            f"<b>{track.get('artist', '')} — {track.get('title', '')}</b>\n"
            f"◷ {track.get('duration_fmt', '')}\n\n"
            f"♪ Треков в базе: {count}"
        )
    else:
        text = (
            f"{icon} <b>{label} LIVE</b>\n\n"
            f"♪ Треков в базе: <b>{count}</b>\n\n"
            f"{t(lang, 'live_pick_action')}"
        )

    rows = []
    if count > 0:
        rows.append([
            InlineKeyboardButton(
                text=t(lang, "live_play"),
                callback_data=LiveCb(act="play", ch=channel).pack(),
            ),
            InlineKeyboardButton(
                text=t(lang, "live_shuffle"),
                callback_data=LiveCb(act="shuf", ch=channel).pack(),
            ),
        ])
    rows.append([InlineKeyboardButton(text="◁", callback_data="action:start")])
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")


@router.callback_query(lambda c: c.data == "radio:tequila")
async def handle_tequila_live(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    await _send_live_menu(callback.message, user.language, "tequila")


@router.callback_query(lambda c: c.data == "radio:fullmoon")
async def handle_fullmoon_live(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    await _send_live_menu(callback.message, user.language, "fullmoon")


@router.callback_query(LiveCb.filter(F.act.in_({"play", "shuf"})))
async def handle_live_play(callback: CallbackQuery, callback_data: LiveCb) -> None:
    """Send a batch of tracks from the channel as audio files."""
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language
    channel = callback_data.ch
    shuffle = callback_data.act == "shuf"
    label = "TEQUILA" if channel == "tequila" else "FULLMOON"

    async with async_session() as session:
        q = (
            select(Track)
            .where(Track.channel == channel, Track.file_id.is_not(None))
        )
        if shuffle:
            q = q.order_by(func.random())
        else:
            q = q.order_by(Track.created_at.desc())
        q = q.limit(_LIVE_BATCH)
        result = await session.execute(q)
        tracks = list(result.scalars().all())

    if not tracks:
        await callback.message.answer(t(lang, "live_no_tracks"))
        return

    mode = t(lang, "live_shuffle_mode") if shuffle else t(lang, "live_play_mode")
    await callback.message.answer(
        f"{'●' if channel == 'tequila' else '◑'} <b>{label}</b> — {mode} ({len(tracks)} треков)",
        parse_mode="HTML",
    )

    for tr in tracks:
        try:
            dur_str = f"{tr.duration // 60}:{tr.duration % 60:02d}" if tr.duration else "?:??"
            await callback.message.answer_audio(
                audio=tr.file_id,
                title=tr.title or "Unknown",
                performer=tr.artist or label,
                duration=tr.duration,
                caption=f"◷ {dur_str} · {label}",
            )
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.warning("Live play skip %s: %s", tr.source_id, e)


# ── Auto-capture channel posts ──────────────────────────────────────────

def _channel_label(chat_id: int) -> str | None:
    """Return live label for a channel chat_id, or None."""
    teq = settings.TEQUILA_CHANNEL
    ful = settings.FULLMOON_CHANNEL
    cid = str(chat_id)
    if teq and (cid == teq or cid == teq.lstrip("@")):
        return "tequila"
    if ful and (cid == ful or cid == ful.lstrip("@")):
        return "fullmoon"
    return None


@router.channel_post()
async def handle_channel_post(message: Message) -> None:
    """Auto-capture audio posted to TEQUILA/FULLMOON channels."""
    if not message.audio:
        return
    label = _channel_label(message.chat.id)
    if not label:
        return
    audio = message.audio
    source_id = f"tg_{message.chat.id}_{message.message_id}"
    await upsert_track(
        source_id=source_id,
        title=audio.title or audio.file_name or "Unknown",
        artist=audio.performer or "",
        duration=audio.duration,
        file_id=audio.file_id,
        source="channel",
        channel=label,
    )
    logger.info("Auto-captured audio %s → %s", source_id, label)


@router.callback_query(lambda c: c.data == "radio:automix")
async def handle_automix(callback: CallbackQuery) -> None:
    """Show genre selection keyboard before creating a mix."""
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language

    # Fetch distinct genres from DB
    async with async_session() as session:
        result = await session.execute(
            select(distinct(Track.genre))
            .where(Track.genre.is_not(None), Track.genre != "")
            .order_by(Track.genre)
        )
        db_genres = [row[0] for row in result.all() if row[0]]

    genres = db_genres if db_genres else _DEFAULT_GENRES

    rows = []
    pair: list[InlineKeyboardButton] = []
    for g in genres:
        pair.append(InlineKeyboardButton(
            text=g, callback_data=MixCb(act="go", genre=g).pack(),
        ))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)

    # "All genres" button
    rows.append([InlineKeyboardButton(
        text=t(lang, "automix_all_genres"),
        callback_data=MixCb(act="go", genre="all").pack(),
    )])
    rows.append([InlineKeyboardButton(text="◁", callback_data="action:start")])

    await callback.message.answer(
        t(lang, "automix_pick_genre"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML",
    )


@router.callback_query(MixCb.filter(F.act == "go"))
async def handle_automix_go(callback: CallbackQuery, callback_data: MixCb) -> None:
    """Download tracks for the chosen genre and create a mix."""
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language
    genre = callback_data.genre

    status = await callback.message.answer(
        t(lang, "automix_generating"), parse_mode="HTML"
    )

    # Pick tracks from DB filtered by genre
    async with async_session() as session:
        q = select(Track).where(Track.source_id.is_not(None))
        if genre != "all":
            q = q.where(Track.genre == genre)
        q = q.order_by(func.random()).limit(6)
        result = await session.execute(q)
        tracks = list(result.scalars().all())

    if len(tracks) < 2:
        await status.edit_text(t(lang, "automix_no_tracks"))
        return

    # Download all tracks
    downloaded_paths: list[Path] = []
    try:
        for tr in tracks:
            try:
                mp3 = await download_track(tr.source_id, bitrate=192)
                downloaded_paths.append(mp3)
            except Exception as e:
                logger.warning("AutoMix: skip track %s: %s", tr.source_id, e)

        if len(downloaded_paths) < 2:
            await status.edit_text(t(lang, "automix_no_tracks"))
            return

        # Create mix
        from mixer.automix import create_mix

        mix_path = settings.DOWNLOAD_DIR / "automix_latest.mp3"
        crossfade = 7
        await create_mix(downloaded_paths, mix_path, crossfade_ms=crossfade * 1000)

        mix_size = mix_path.stat().st_size
        if mix_size > settings.MAX_FILE_SIZE:
            await status.edit_text(t(lang, "automix_error"))
            return

        await callback.message.answer_audio(
            audio=FSInputFile(mix_path),
            title=f"AUTO MIX — {genre.upper()}" if genre != "all" else "AUTO MIX — BLACK ROOM",
            performer="BLACK ROOM DJ",
        )
        await status.edit_text(
            t(lang, "automix_done", count=len(downloaded_paths), crossfade=crossfade),
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error("AutoMix error: %s", e)
        await status.edit_text(t(lang, "automix_error"))
    finally:
        # Cleanup downloaded files
        from bot.services.downloader import cleanup_file
        for p in downloaded_paths:
            cleanup_file(p)
        mix_out = settings.DOWNLOAD_DIR / "automix_latest.mp3"
        if mix_out.exists():
            mix_out.unlink(missing_ok=True)


# Триггер "что играет" / "что за трек"
@router.message(lambda m: m.text and any(
    phrase in m.text.lower() for phrase in ("что играет", "что за трек", "what's playing")
))
async def handle_whats_playing(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    lang = user.language

    tequila = await _get_current_track("tequila")
    fullmoon = await _get_current_track("fullmoon")

    lines = []
    if tequila:
        lines.append(f"▸ TEQUILA: <b>{tequila.get('artist')} — {tequila.get('title')}</b>")
    if fullmoon:
        lines.append(f"◑ FULLMOON: <b>{fullmoon.get('artist')} — {fullmoon.get('title')}</b>")

    if not lines:
        await message.answer(t(lang, "radio_nothing_playing"))
    else:
        await message.answer("\n".join(lines), parse_mode="HTML")


# Триггеры управления радио: "стоп", "пауза", "дальше", "скип", "next", "stop", "pause"
@router.message(lambda m: m.text and m.text.strip().lower() in (
    "стоп", "stop", "пауза", "pause", "дальше", "скип", "next", "skip", "выключи"
))
async def handle_radio_control(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    lang = user.language
    cmd = message.text.strip().lower()

    if cmd in ("стоп", "stop", "выключи"):
        await cache.redis.publish("radio:cmd", "stop")
        await message.answer(t(lang, "radio_stop"))

    elif cmd in ("пауза", "pause"):
        await cache.redis.publish("radio:cmd", "pause")
        await message.answer(t(lang, "radio_pause"))

    elif cmd in ("дальше", "скип", "next", "skip"):
        await cache.redis.publish("radio:cmd", "skip")
        await message.answer(t(lang, "radio_skip"))
