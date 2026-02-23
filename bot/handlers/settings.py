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

_QUALITY_KEYBOARD_FREE = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="128 kbps", callback_data="quality:128"),
            InlineKeyboardButton(text="192 kbps", callback_data="quality:192"),
        ],
        [
            InlineKeyboardButton(text="▣ 320 kbps (Premium)", callback_data="quality:320"),
        ],
    ]
)

_QUALITY_KEYBOARD_PREMIUM = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="128 kbps", callback_data="quality:128"),
            InlineKeyboardButton(text="192 kbps", callback_data="quality:192"),
            InlineKeyboardButton(text="★ 320 kbps", callback_data="quality:320"),
        ]
    ]
)


@router.message(Command("settings"))
async def cmd_settings(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    lang = user.language
    kb = _QUALITY_KEYBOARD_PREMIUM if user.is_premium else _QUALITY_KEYBOARD_FREE
    await message.answer(
        t(lang, "settings_quality", current=user.quality),
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data and c.data.startswith("quality:"))
async def handle_quality_change(callback: CallbackQuery) -> None:
    quality = callback.data.split(":")[1]
    if quality not in ("128", "192", "320"):
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
