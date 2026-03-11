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


async def _award_premium_badge(session, user_id: int) -> None:
    """Add 'premium' badge if not already present."""
    db_user = await session.get(User, user_id)
    if db_user:
        badges = db_user.badges or []
        if "premium" not in badges:
            db_user.badges = badges + ["premium"]

router = Router()

# ── Payload constants ─────────────────────────────────────────────────────
_PAYLOAD_PREMIUM_30D = "premium_30d"
_PAYLOAD_PREMIUM_90D = "premium_90d"
_PAYLOAD_PREMIUM_365D = "premium_365d"
_PAYLOAD_TRIAL_7D = "trial_7d"
_PAYLOAD_FLAC_1 = "flac_1"
_PAYLOAD_FLAC_10 = "flac_10"
_PAYLOAD_NO_ADS_24H = "no_ads_24h"
_PAYLOAD_GIFT_PREFIX = "gift_"

# ── Prices (Stars) ────────────────────────────────────────────────────────
_PRICE_TRIAL_7D = 50
_PRICE_FLAC_1 = 5
_PRICE_FLAC_10 = 40       # −20% vs 10×5
_PRICE_NO_ADS_24H = 3
_PRICE_PREMIUM_90D = 350  # −22%
_PRICE_PREMIUM_365D = 1000  # −44%


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
                    text=t(lang, "premium_90d_btn", price=_PRICE_PREMIUM_90D),
                    callback_data="premium:buy:90d",
                )],
                [InlineKeyboardButton(
                    text=t(lang, "premium_365d_btn", price=_PRICE_PREMIUM_365D),
                    callback_data="premium:buy:365d",
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
                [InlineKeyboardButton(
                    text=t(lang, "flac_10_btn", price=_PRICE_FLAC_10),
                    callback_data="premium:buy:flac10",
                )],
                [InlineKeyboardButton(
                    text=t(lang, "gift_premium_btn"),
                    callback_data="premium:gift",
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
            await _award_premium_badge(session, user.id)
            await session.commit()
            logger.info("Premium 30d activated for user %s until %s", user.id, premium_until.isoformat())
            await message.answer(t(lang, "premium_pay_success"), parse_mode="HTML")

        elif payload == _PAYLOAD_TRIAL_7D:
            premium_until = now + timedelta(days=7)
            await session.execute(
                update(User).where(User.id == user.id)
                .values(is_premium=True, premium_until=premium_until)
            )
            await _award_premium_badge(session, user.id)
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

        elif payload == _PAYLOAD_FLAC_10:
            await session.execute(
                update(User).where(User.id == user.id)
                .values(flac_credits=User.flac_credits + 10)
            )
            await session.commit()
            logger.info("FLAC credit +10 for user %s", user.id)
            await message.answer(t(lang, "flac_10_success"), parse_mode="HTML")

        elif payload == _PAYLOAD_PREMIUM_90D:
            premium_until = now + timedelta(days=90)
            await session.execute(
                update(User).where(User.id == user.id)
                .values(is_premium=True, premium_until=premium_until)
            )
            await _award_premium_badge(session, user.id)
            await session.commit()
            logger.info("Premium 90d activated for user %s", user.id)
            await message.answer(t(lang, "premium_90d_success"), parse_mode="HTML")

        elif payload == _PAYLOAD_PREMIUM_365D:
            premium_until = now + timedelta(days=365)
            await session.execute(
                update(User).where(User.id == user.id)
                .values(is_premium=True, premium_until=premium_until)
            )
            await _award_premium_badge(session, user.id)
            await session.commit()
            logger.info("Premium 365d activated for user %s", user.id)
            await message.answer(t(lang, "premium_365d_success"), parse_mode="HTML")

        elif payload.startswith(_PAYLOAD_GIFT_PREFIX):
            # Gift premium for another user
            target_id_str = payload[len(_PAYLOAD_GIFT_PREFIX):]
            try:
                target_id = int(target_id_str)
            except ValueError:
                await session.commit()
                return
            premium_until = now + timedelta(days=30)
            await session.execute(
                update(User).where(User.id == target_id)
                .values(is_premium=True, premium_until=premium_until)
            )
            await _award_premium_badge(session, target_id)
            await session.commit()
            logger.info("Gift Premium 30d for user %s from %s", target_id, user.id)
            await message.answer(t(lang, "gift_success", target=target_id), parse_mode="HTML")
            # Notify recipient
            try:
                await message.bot.send_message(target_id, t("ru", "gift_received", from_name=user.first_name or str(user.id)), parse_mode="HTML")
            except Exception:
                pass

        else:
            await session.commit()
            logger.warning("Unknown payment payload: %s from user %s", payload, user.id)


# ── Bundle invoice handlers ──────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "premium:buy:90d")
async def handle_premium_90d(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language
    await callback.message.answer_invoice(
        title=t(lang, "premium_90d_title"),
        description=t(lang, "premium_90d_desc"),
        payload=_PAYLOAD_PREMIUM_90D,
        currency="XTR",
        prices=[LabeledPrice(label="Premium 90d", amount=_PRICE_PREMIUM_90D)],
    )


@router.callback_query(lambda c: c.data == "premium:buy:365d")
async def handle_premium_365d(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language
    await callback.message.answer_invoice(
        title=t(lang, "premium_365d_title"),
        description=t(lang, "premium_365d_desc"),
        payload=_PAYLOAD_PREMIUM_365D,
        currency="XTR",
        prices=[LabeledPrice(label="Premium 365d", amount=_PRICE_PREMIUM_365D)],
    )


@router.callback_query(lambda c: c.data == "premium:buy:flac10")
async def handle_flac10_buy(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language
    await callback.message.answer_invoice(
        title=t(lang, "flac_10_title"),
        description=t(lang, "flac_10_desc"),
        payload=_PAYLOAD_FLAC_10,
        currency="XTR",
        prices=[LabeledPrice(label="10 FLAC tracks", amount=_PRICE_FLAC_10)],
    )


# ── Gift Premium ─────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "premium:gift")
async def handle_gift_premium(callback: CallbackQuery) -> None:
    await callback.answer()
    user = await get_or_create_user(callback.from_user)
    lang = user.language
    await callback.message.answer(t(lang, "gift_prompt"), parse_mode="HTML")


from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup


class GiftState(StatesGroup):
    waiting_target = State()


@router.message(Command("gift"))
async def cmd_gift(message: Message, state: FSMContext) -> None:
    user = await get_or_create_user(message.from_user)
    await message.answer(t(user.language, "gift_prompt"), parse_mode="HTML")
    await state.set_state(GiftState.waiting_target)


@router.message(GiftState.waiting_target)
async def handle_gift_target(message: Message, state: FSMContext) -> None:
    user = await get_or_create_user(message.from_user)
    lang = user.language
    target_text = message.text.strip().lstrip("@")
    await state.clear()

    # Resolve target user
    from sqlalchemy import select, func as sqla_func
    async with async_session() as session:
        try:
            target_id = int(target_text)
            result = await session.execute(select(User).where(User.id == target_id))
        except ValueError:
            result = await session.execute(
                select(User).where(sqla_func.lower(User.username) == target_text.lower())
            )
        target_user = result.scalar_one_or_none()

    if not target_user:
        await message.answer(t(lang, "gift_user_not_found"), parse_mode="HTML")
        return

    # Send invoice with gift payload
    await message.answer_invoice(
        title=t(lang, "gift_invoice_title"),
        description=t(lang, "gift_invoice_desc", target=target_user.first_name or str(target_user.id)),
        payload=f"{_PAYLOAD_GIFT_PREFIX}{target_user.id}",
        currency="XTR",
        prices=[LabeledPrice(label="Gift Premium 30d", amount=settings.PREMIUM_STAR_PRICE)],
    )


# ── Promo Code ───────────────────────────────────────────────────────────

@router.message(Command("promo"))
async def cmd_promo(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    lang = user.language
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(t(lang, "promo_enter_code"), parse_mode="HTML")
        return
    code = parts[1].strip()
    from bot.services.promo_service import activate_promo
    success, msg_key = await activate_promo(code, user.id)
    await message.answer(t(lang, msg_key), parse_mode="HTML")
