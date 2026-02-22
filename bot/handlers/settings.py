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

_QUALITY_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="128 kbps", callback_data="quality:128"),
            InlineKeyboardButton(text="192 kbps", callback_data="quality:192"),
            InlineKeyboardButton(text="320 kbps", callback_data="quality:320"),
        ]
    ]
)


@router.message(Command("settings"))
async def cmd_settings(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    lang = user.language
    await message.answer(
        t(lang, "settings_quality", current=user.quality),
        reply_markup=_QUALITY_KEYBOARD,
        parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data and c.data.startswith("quality:"))
async def handle_quality_change(callback: CallbackQuery) -> None:
    quality = callback.data.split(":")[1]
    if quality not in ("128", "192", "320"):
        await callback.answer()
        return

    async with async_session() as session:
        await session.execute(
            update(User).where(User.id == callback.from_user.id).values(quality=quality)
        )
        await session.commit()

    user = await get_or_create_user(callback.from_user)
    await callback.answer()
    await callback.message.edit_text(
        t(user.language, "settings_quality_changed", quality=quality)
    )
