"""
premium.py — Premium-подписка через Telegram Stars.
"""
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)
from sqlalchemy import update

from bot.config import settings
from bot.db import get_or_create_user
from bot.i18n import t
from bot.models.base import async_session
from bot.models.user import User

logger = logging.getLogger(__name__)

router = Router()


@router.callback_query(lambda c: c.data == "action:premium")
async def handle_premium(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language

    if user.is_premium:
        until = ""
        if user.premium_until:
            until = user.premium_until.strftime("%d.%m.%Y")
        text = t(lang, "premium_active", until=until)
        keyboard = None
    else:
        text = t(lang, "premium_info")
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text=t(lang, "premium_pay_button", price=settings.PREMIUM_STAR_PRICE),
                    callback_data="premium:buy:stars",
                )],
            ]
        )

    await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(lambda c: c.data == "premium:buy:stars")
async def handle_premium_buy(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language

    # Send Telegram Stars invoice
    await callback.message.answer_invoice(
        title=t(lang, "premium_invoice_title"),
        description=t(lang, "premium_invoice_desc"),
        payload="premium_30d",
        currency="XTR",  # Telegram Stars currency code
        prices=[LabeledPrice(label="Premium", amount=settings.PREMIUM_STAR_PRICE)],
    )


@router.pre_checkout_query()
async def handle_pre_checkout(pre_checkout_query: PreCheckoutQuery) -> None:
    """Always approve — Telegram Stars don't have complex validation."""
    await pre_checkout_query.answer(ok=True)


@router.message(lambda m: m.successful_payment is not None)
async def handle_successful_payment(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    lang = user.language

    premium_until = datetime.now(timezone.utc) + timedelta(days=settings.PREMIUM_DAYS)

    async with async_session() as session:
        await session.execute(
            update(User)
            .where(User.id == user.id)
            .values(is_premium=True, premium_until=premium_until)
        )
        await session.commit()

    logger.info(
        "Premium activated for user %s until %s (Stars: %s)",
        user.id,
        premium_until.isoformat(),
        message.successful_payment.total_amount,
    )

    await message.answer(t(lang, "premium_pay_success"), parse_mode="HTML")
