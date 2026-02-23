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
                    InlineKeyboardButton(text=_label("128", "128 kbps"), callback_data="quality:128"),
                    InlineKeyboardButton(text=_label("192", "192 kbps"), callback_data="quality:192"),
                    InlineKeyboardButton(text=_label("320", "★ 320 kbps"), callback_data="quality:320"),
                ]
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
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
async def cmd_settings(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    lang = user.language
    kb = _quality_keyboard(user.is_premium, user.quality)
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
