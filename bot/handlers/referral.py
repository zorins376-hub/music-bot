"""
referral.py — Referral system: invite friends → earn bonus tracks & premium days.

E-01:
- /referral — show referral link + stats
- ref_<user_id> deep-link handling (called from start.py)
- Bonus: +5 daily tracks per referral (up to +50)
- 10 referrals → 3 days Premium
- 50 referrals → 30 days Premium
- Referral counts only after invitee downloads 3+ tracks
"""
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import update

from bot.db import get_or_create_user
from bot.i18n import t
from bot.models.base import async_session
from bot.models.user import User

logger = logging.getLogger(__name__)

router = Router()

_BONUS_PER_REF = 5
_MAX_BONUS = 50
_PREMIUM_10_DAYS = 3
_PREMIUM_50_DAYS = 30
_MIN_DOWNLOADS_TO_COUNT = 3


@router.message(Command("referral"))
async def cmd_referral(message: Message) -> None:
    user = await get_or_create_user(message.from_user)
    lang = user.language

    bot_me = await message.bot.me()
    link = f"https://t.me/{bot_me.username}?start=ref_{user.id}"

    await message.answer(
        t(lang, "referral_info",
          link=link,
          count=user.referral_count,
          bonus=user.referral_bonus_tracks),
        parse_mode="HTML",
    )


async def process_referral(message: Message, referrer_id_str: str) -> None:
    """Handle ref_<user_id> deep-link. Called from start.py."""
    try:
        referrer_id = int(referrer_id_str)
    except (ValueError, TypeError):
        return

    new_user = await get_or_create_user(message.from_user)

    # Don't self-refer
    if new_user.id == referrer_id:
        return

    # Already referred
    if new_user.referred_by is not None:
        return

    async with async_session() as session:
        referrer = await session.get(User, referrer_id)
        if not referrer:
            return

        # Mark the new user as referred
        await session.execute(
            update(User).where(User.id == new_user.id).values(referred_by=referrer_id)
        )
        await session.commit()

    lang = new_user.language
    await message.answer(t(lang, "referral_welcome"))


async def check_referral_activation(user_id: int, download_count: int) -> None:
    """Called after a download. Activate referral bonus when invitee reaches 3 downloads."""
    if download_count != _MIN_DOWNLOADS_TO_COUNT:
        return

    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user or not user.referred_by:
            return

        referrer = await session.get(User, user.referred_by)
        if not referrer:
            return

        # Increment referrer's count
        new_count = referrer.referral_count + 1
        new_bonus = min(referrer.referral_bonus_tracks + _BONUS_PER_REF, _MAX_BONUS)

        values = {"referral_count": new_count, "referral_bonus_tracks": new_bonus}

        # Premium rewards
        if new_count == 10:
            until = datetime.now(timezone.utc) + timedelta(days=_PREMIUM_10_DAYS)
            if not referrer.premium_until or referrer.premium_until < until:
                values["is_premium"] = True
                values["premium_until"] = until
        elif new_count == 50:
            until = datetime.now(timezone.utc) + timedelta(days=_PREMIUM_50_DAYS)
            if not referrer.premium_until or referrer.premium_until < until:
                values["is_premium"] = True
                values["premium_until"] = until

        await session.execute(
            update(User).where(User.id == referrer.id).values(**values)
        )
        await session.commit()

    logger.info("Referral activated: user %s referred by %s (count=%d)", user_id, referrer.id, new_count)
