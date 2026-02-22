"""
premium.py — Premium-подписка.

MVP: информация и заглушка.
v2.0: Telegram Stars payments + YooKassa.
"""
from aiogram import Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.db import get_or_create_user
from bot.i18n import t

router = Router()


@router.callback_query(lambda c: c.data == "action:premium")
async def handle_premium(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language

    if user.is_premium:
        text = t(lang, "premium_active")
        keyboard = None
    else:
        text = t(lang, "premium_info")
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⭐ Оплатить Telegram Stars", callback_data="premium:buy:stars")],
            ]
        )

    await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(lambda c: c.data == "premium:buy:stars")
async def handle_premium_buy(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    # TODO v2.0: интеграция Telegram Stars invoice
    await callback.message.answer(
        t(user.language, "premium_soon"), parse_mode="HTML"
    )
