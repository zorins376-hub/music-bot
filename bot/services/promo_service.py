"""
promo_service.py — PromoCode CRUD & activation logic.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from bot.models.base import async_session
from bot.models.promo_code import PromoActivation, PromoCode
from bot.models.user import User

logger = logging.getLogger(__name__)

_TYPE_ACTIONS = {
    "premium_7d": {"field": "premium", "days": 7},
    "premium_30d": {"field": "premium", "days": 30},
    "flac_5": {"field": "flac", "credits": 5},
}


async def create_promo(code: str, promo_type: str, max_uses: int, created_by: int) -> PromoCode | None:
    async with async_session() as session:
        existing = await session.execute(select(PromoCode).where(PromoCode.code == code))
        if existing.scalar_one_or_none():
            return None
        promo = PromoCode(code=code, promo_type=promo_type, uses_left=max_uses, max_uses=max_uses, created_by=created_by)
        session.add(promo)
        await session.commit()
        await session.refresh(promo)
        return promo


async def list_promos() -> list[dict]:
    async with async_session() as session:
        result = await session.execute(select(PromoCode).order_by(PromoCode.created_at.desc()).limit(50))
        return [
            {"code": p.code, "type": p.promo_type, "uses_left": p.uses_left, "max_uses": p.max_uses}
            for p in result.scalars().all()
        ]


async def activate_promo(code: str, user_id: int) -> tuple[bool, str]:
    """Activate a promo code for a user. Returns (success, message_key)."""
    async with async_session() as session:
        result = await session.execute(select(PromoCode).where(PromoCode.code == code))
        promo = result.scalar_one_or_none()
        if not promo:
            return False, "promo_not_found"
        if promo.uses_left <= 0:
            return False, "promo_expired"

        # Check if already activated by this user
        existing = await session.execute(
            select(PromoActivation).where(
                PromoActivation.promo_id == promo.id,
                PromoActivation.user_id == user_id,
            )
        )
        if existing.scalar_one_or_none():
            return False, "promo_already_used"

        # Apply reward
        now = datetime.now(timezone.utc)
        action = _TYPE_ACTIONS.get(promo.promo_type)
        if not action:
            return False, "promo_not_found"

        if action.get("field") == "premium":
            days = action["days"]
            premium_until = now + timedelta(days=days)
            await session.execute(
                update(User).where(User.id == user_id).values(is_premium=True, premium_until=premium_until)
            )
        elif action.get("field") == "flac":
            credits = action["credits"]
            await session.execute(
                update(User).where(User.id == user_id).values(flac_credits=User.flac_credits + credits)
            )

        # Record activation
        session.add(PromoActivation(promo_id=promo.id, user_id=user_id))
        promo.uses_left -= 1
        await session.commit()

        logger.info("Promo %s activated by user %s (type=%s)", code, user_id, promo.promo_type)
        return True, f"promo_success_{promo.promo_type}"
