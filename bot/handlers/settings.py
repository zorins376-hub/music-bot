"""
settings.py — Настройки пользователя: качество аудио.
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import update

from bot.db import get_or_create_user
from bot.i18n import t
from bot.models.base import async_session
from bot.models.user import User

router = Router()


def _quality_keyboard(is_premium: bool, current: str) -> InlineKeyboardMarkup:
    """Build quality keyboard with checkmark on current selection."""
    def _label(val: str, text: str) -> str:
        return f"✓ {text}" if current == val else text

    if is_premium:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text=_label("auto", "⚡ Auto"), callback_data="quality:auto"),
                ],
                [
                    InlineKeyboardButton(text=_label("128", "128 kbps"), callback_data="quality:128"),
                    InlineKeyboardButton(text=_label("192", "192 kbps"), callback_data="quality:192"),
                    InlineKeyboardButton(text=_label("320", "★ 320 kbps"), callback_data="quality:320"),
                ]
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=_label("auto", "⚡ Auto"), callback_data="quality:auto"),
            ],
            [
                InlineKeyboardButton(text=_label("128", "128 kbps"), callback_data="quality:128"),
                InlineKeyboardButton(text=_label("192", "192 kbps"), callback_data="quality:192"),
            ],
            [
                InlineKeyboardButton(text="▣ 320 kbps (Premium)", callback_data="quality:320"),
            ],
        ]
    )


@router.message(Command("settings"))
async def cmd_settings_v2(message: Message) -> None:
    """Show full settings menu with quality + TTS toggle."""
    user = await get_or_create_user(message.from_user)
    lang = user.language
    raw_text = message.text if isinstance(message.text, str) else ""
    text = (raw_text or "").strip()
    args = text.split()
    if len(args) >= 3 and args[1].lower() == "releases":
        mode = args[2].lower()
        if mode not in ("on", "off"):
            await message.answer(t(lang, "settings_releases_usage"))
            return
        new_value = mode == "on"
        async with async_session() as session:
            await session.execute(
                update(User).where(User.id == user.id).values(release_radar_enabled=new_value)
            )
            await session.commit()
        await message.answer(
            t(lang, "settings_releases_updated_on" if new_value else "settings_releases_updated_off")
        )
        return

    tts_on = (user.fav_vibe or "") != "tts_off"  # reuse field as TTS pref
    kb = _settings_keyboard(user.is_premium, user.quality, tts_on, bool(user.release_radar_enabled), lang)
    await message.answer(
        t(lang, "settings_quality", current=user.quality),
        reply_markup=kb,
        parse_mode="HTML",
    )


cmd_settings = cmd_settings_v2


def _settings_keyboard(
    is_premium: bool, current: str, tts_on: bool, releases_on: bool, lang: str
) -> InlineKeyboardMarkup:
    rows = _quality_keyboard(is_premium, current).inline_keyboard
    tts_label = t(lang, "settings_tts_on") if tts_on else t(lang, "settings_tts_off")
    rows.append([InlineKeyboardButton(text=tts_label, callback_data="settings:tts")])
    releases_label = t(lang, "settings_releases_on") if releases_on else t(lang, "settings_releases_off")
    rows.append([InlineKeyboardButton(text=releases_label, callback_data="settings:releases")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(lambda c: c.data == "settings:tts")
async def handle_tts_toggle(callback: CallbackQuery) -> None:
    user = await get_or_create_user(callback.from_user)
    lang = user.language
    current_off = (user.fav_vibe or "") == "tts_off"
    new_vibe = None if current_off else "tts_off"
    async with async_session() as session:
        await session.execute(
            update(User).where(User.id == user.id).values(fav_vibe=new_vibe)
        )
        await session.commit()
    tts_now = current_off  # was off, now on
    await callback.answer(
        t(lang, "settings_tts_toggled_on" if tts_now else "settings_tts_toggled_off"),
        show_alert=False,
    )
    kb = _settings_keyboard(user.is_premium, user.quality, tts_now, bool(user.release_radar_enabled), lang)
    await callback.message.edit_reply_markup(reply_markup=kb)


@router.callback_query(lambda c: c.data == "settings:releases")
async def handle_releases_toggle(callback: CallbackQuery) -> None:
    user = await get_or_create_user(callback.from_user)
    lang = user.language
    new_value = not bool(user.release_radar_enabled)

    async with async_session() as session:
        await session.execute(
            update(User).where(User.id == user.id).values(release_radar_enabled=new_value)
        )
        await session.commit()

    await callback.answer(
        t(lang, "settings_releases_updated_on" if new_value else "settings_releases_updated_off"),
        show_alert=False,
    )
    tts_on = (user.fav_vibe or "") != "tts_off"
    kb = _settings_keyboard(user.is_premium, user.quality, tts_on, new_value, lang)
    await callback.message.edit_reply_markup(reply_markup=kb)


@router.callback_query(lambda c: c.data and c.data.startswith("quality:"))
async def handle_quality_change(callback: CallbackQuery) -> None:
    quality = callback.data.split(":")[1]
    if quality not in ("auto", "128", "192", "320"):
        await callback.answer()
        return

    user = await get_or_create_user(callback.from_user)
    lang = user.language

    # 320 kbps — Premium only
    if quality == "320" and not user.is_premium:
        await callback.answer(t(lang, "quality_premium_only"), show_alert=True)
        return

    async with async_session() as session:
        await session.execute(
            update(User).where(User.id == callback.from_user.id).values(quality=quality)
        )
        await session.commit()

    await callback.answer()
    await callback.message.edit_text(
        t(lang, "settings_quality_changed", quality=quality)
    )
