"""
radio.py — TEQUILA LIVE, FULLMOON LIVE, AUTO MIX handlers.

MVP: показывает статус эфира и текущий трек из Redis (если стример запущен).
v1.1: полноценная интеграция с Pyrogram + pytgcalls streamer.
"""
import logging

from aiogram import Router
from aiogram.types import CallbackQuery, Message

from bot.db import get_or_create_user
from bot.i18n import t
from bot.services.cache import cache

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
            f"🔴 <b>TEQUILA LIVE</b>\n\n"
            f"▶️ Сейчас играет:\n"
            f"<b>{track.get('artist', '')} — {track.get('title', '')}</b>\n"
            f"⏱ {track.get('duration_fmt', '')}"
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
            f"🌕 <b>FULLMOON LIVE</b>\n\n"
            f"▶️ Сейчас играет:\n"
            f"<b>{track.get('artist', '')} — {track.get('title', '')}</b>\n"
            f"⏱ {track.get('duration_fmt', '')}"
        )
    else:
        text = t(lang, "radio_fullmoon_offline")

    await callback.message.answer(text, parse_mode="HTML")


@router.callback_query(lambda c: c.data == "radio:automix")
async def handle_automix(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    await callback.message.answer(
        t(user.language, "automix_coming_soon"), parse_mode="HTML"
    )


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
        lines.append(f"▶️ TEQUILA: <b>{tequila.get('artist')} — {tequila.get('title')}</b>")
    if fullmoon:
        lines.append(f"🌕 FULLMOON: <b>{fullmoon.get('artist')} — {fullmoon.get('title')}</b>")

    if not lines:
        await message.answer(t(lang, "radio_nothing_playing"))
    else:
        await message.answer("\n".join(lines), parse_mode="HTML")


# Триггеры управления радио: "стоп", "пауза", "дальше", "скип", "next", "stop", "pause"
@router.message(lambda m: m.text and m.text.strip().lower() in (
    "стоп", "stop", "пауза", "pause", "дальше", "скип", "next", "skip"
))
async def handle_radio_control(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    lang = user.language
    cmd = message.text.strip().lower()

    if cmd in ("стоп", "stop"):
        # v1.1: отправить команду стримеру через Redis pub/sub
        await cache.redis.publish("radio:cmd", "stop")
        await message.answer(t(lang, "radio_stop"))

    elif cmd in ("пауза", "pause"):
        await cache.redis.publish("radio:cmd", "pause")
        await message.answer(t(lang, "radio_pause"))

    elif cmd in ("дальше", "скип", "next", "skip"):
        await cache.redis.publish("radio:cmd", "skip")
        await message.answer(t(lang, "radio_skip"))
