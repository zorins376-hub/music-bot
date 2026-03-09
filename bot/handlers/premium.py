"""
premium.py — Premium-подписка и микро-платежи через Telegram Stars.

F-01: Расширенный Premium (FLAC, батч, приоритет, без рекламы).
F-02: Разовые покупки Stars (FLAC-трек, без рекламы 24ч, trial Premium).
"""
import logging
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
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
from bot.models.track import Payment
from bot.models.user import User

logger = logging.getLogger(__name__)

router = Router()

# ── Payload constants ─────────────────────────────────────────────────────
_PAYLOAD_PREMIUM_30D = "premium_30d"
_PAYLOAD_TRIAL_7D = "trial_7d"
_PAYLOAD_FLAC_1 = "flac_1"
_PAYLOAD_NO_ADS_24H = "no_ads_24h"

# ── Prices (Stars) ────────────────────────────────────────────────────────
_PRICE_TRIAL_7D = 50
_PRICE_FLAC_1 = 5
_PRICE_NO_ADS_24H = 3


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
                [InlineKeyboardButton(
                    text=t(lang, "micro_trial_btn", price=_PRICE_TRIAL_7D),
                    callback_data="premium:buy:trial7d",
                )],
                [InlineKeyboardButton(
                    text=t(lang, "micro_noads_btn", price=_PRICE_NO_ADS_24H),
                    callback_data="premium:buy:noads24h",
                )],
                [InlineKeyboardButton(
                    text=t(lang, "micro_flac_btn", price=_PRICE_FLAC_1),
                    callback_data="premium:buy:flac1",
                )],
            ]
        )

    await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")


# ── Invoice generators ────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "premium:buy:stars")
async def handle_premium_buy(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language

    await callback.message.answer_invoice(
        title=t(lang, "premium_invoice_title"),
        description=t(lang, "premium_invoice_desc"),
        payload=_PAYLOAD_PREMIUM_30D,
        currency="XTR",
        prices=[LabeledPrice(label="Premium 30d", amount=settings.PREMIUM_STAR_PRICE)],
    )


@router.callback_query(lambda c: c.data == "premium:buy:trial7d")
async def handle_trial_buy(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language

    await callback.message.answer_invoice(
        title=t(lang, "micro_trial_title"),
        description=t(lang, "micro_trial_desc"),
        payload=_PAYLOAD_TRIAL_7D,
        currency="XTR",
        prices=[LabeledPrice(label="Premium 7d trial", amount=_PRICE_TRIAL_7D)],
    )


@router.callback_query(lambda c: c.data == "premium:buy:noads24h")
async def handle_noads_buy(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language

    await callback.message.answer_invoice(
        title=t(lang, "micro_noads_title"),
        description=t(lang, "micro_noads_desc"),
        payload=_PAYLOAD_NO_ADS_24H,
        currency="XTR",
        prices=[LabeledPrice(label="No ads 24h", amount=_PRICE_NO_ADS_24H)],
    )


@router.callback_query(lambda c: c.data == "premium:buy:flac1")
async def handle_flac_buy(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language

    await callback.message.answer_invoice(
        title=t(lang, "micro_flac_title"),
        description=t(lang, "micro_flac_desc"),
        payload=_PAYLOAD_FLAC_1,
        currency="XTR",
        prices=[LabeledPrice(label="1 FLAC track", amount=_PRICE_FLAC_1)],
    )


# ── Payment processing ───────────────────────────────────────────────────

@router.pre_checkout_query()
async def handle_pre_checkout(pre_checkout_query: PreCheckoutQuery) -> None:
    """Approve all Star payments."""
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def handle_successful_payment(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    lang = user.language
    payload = message.successful_payment.invoice_payload
    now = datetime.now(timezone.utc)

    async with async_session() as session:
        # Record payment
        session.add(Payment(
            user_id=user.id,
            amount=message.successful_payment.total_amount,
            currency=message.successful_payment.currency,
            payload=payload,
        ))

        if payload == _PAYLOAD_PREMIUM_30D:
            premium_until = now + timedelta(days=settings.PREMIUM_DAYS)
            await session.execute(
                update(User).where(User.id == user.id)
                .values(is_premium=True, premium_until=premium_until)
            )
            await session.commit()
            logger.info("Premium 30d activated for user %s until %s", user.id, premium_until.isoformat())
            await message.answer(t(lang, "premium_pay_success"), parse_mode="HTML")

        elif payload == _PAYLOAD_TRIAL_7D:
            premium_until = now + timedelta(days=7)
            await session.execute(
                update(User).where(User.id == user.id)
                .values(is_premium=True, premium_until=premium_until)
            )
            await session.commit()
            logger.info("Premium trial 7d for user %s until %s", user.id, premium_until.isoformat())
            await message.answer(t(lang, "micro_trial_success"), parse_mode="HTML")

        elif payload == _PAYLOAD_NO_ADS_24H:
            ad_free_until = now + timedelta(hours=24)
            await session.execute(
                update(User).where(User.id == user.id)
                .values(ad_free_until=ad_free_until)
            )
            await session.commit()
            logger.info("Ad-free 24h for user %s until %s", user.id, ad_free_until.isoformat())
            await message.answer(t(lang, "micro_noads_success"), parse_mode="HTML")

        elif payload == _PAYLOAD_FLAC_1:
            await session.execute(
                update(User).where(User.id == user.id)
                .values(flac_credits=User.flac_credits + 1)
            )
            await session.commit()
            logger.info("FLAC credit +1 for user %s", user.id)
            await message.answer(t(lang, "micro_flac_success"), parse_mode="HTML")

        else:
            await session.commit()
            logger.warning("Unknown payment payload: %s from user %s", payload, user.id)
