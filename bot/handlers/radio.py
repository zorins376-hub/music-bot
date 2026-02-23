"""
radio.py — TEQUILA LIVE, FULLMOON LIVE, AUTO MIX handlers.

Radio: показывает статус эфира и текущий трек из Redis.
AUTO MIX: скачивает случайные треки из БД, миксует и отправляет.
"""
import logging
from pathlib import Path

from aiogram import Router
from aiogram.types import CallbackQuery, FSInputFile, Message
from sqlalchemy import select
from sqlalchemy.sql import func

from bot.db import get_or_create_user
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


async def _get_current_track(channel: str) -> dict | None:
    """Возвращает текущий трек из Redis (заполняется стримером в v1.1)."""
    import json
    data = await cache.redis.get(_CURRENT_TRACK_KEY.format(channel=channel))
    return json.loads(data) if data else None


@router.callback_query(lambda c: c.data == "radio:tequila")
async def handle_tequila_live(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language

    track = await _get_current_track("tequila")
    if track:
        text = (
            f"● <b>TEQUILA LIVE</b>\n\n"
            f"▸ Сейчас играет:\n"
            f"<b>{track.get('artist', '')} — {track.get('title', '')}</b>\n"
            f"◷ {track.get('duration_fmt', '')}"
        )
    else:
        text = t(lang, "radio_tequila_offline")

    await callback.message.answer(text, parse_mode="HTML")


@router.callback_query(lambda c: c.data == "radio:fullmoon")
async def handle_fullmoon_live(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language

    track = await _get_current_track("fullmoon")
    if track:
        text = (
            f"◑ <b>FULLMOON LIVE</b>\n\n"
            f"▸ Сейчас играет:\n"
            f"<b>{track.get('artist', '')} — {track.get('title', '')}</b>\n"
            f"◷ {track.get('duration_fmt', '')}"
        )
    else:
        text = t(lang, "radio_fullmoon_offline")

    await callback.message.answer(text, parse_mode="HTML")


@router.callback_query(lambda c: c.data == "radio:automix")
async def handle_automix(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language

    status = await callback.message.answer(
        t(lang, "automix_generating"), parse_mode="HTML"
    )

    # Pick random tracks from DB — prefer channel tracks (TEQUILA/FULLMOON)
    async with async_session() as session:
        # First try channel tracks
        result = await session.execute(
            select(Track)
            .where(
                Track.source_id.is_not(None),
                Track.channel.in_(("tequila", "fullmoon")),
            )
            .order_by(func.random())
            .limit(6)
        )
        tracks = list(result.scalars().all())

        # Fill remaining slots with any tracks
        if len(tracks) < 6:
            existing_ids = [tr.id for tr in tracks]
            filler = await session.execute(
                select(Track)
                .where(
                    Track.source_id.is_not(None),
                    Track.id.not_in(existing_ids) if existing_ids else True,
                )
                .order_by(func.random())
                .limit(6 - len(tracks))
            )
            tracks.extend(filler.scalars().all())

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
            title="AUTO MIX — BLACK ROOM",
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
