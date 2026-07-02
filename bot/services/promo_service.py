"""
promo_service.py — PromoCode CRUD & activation logic.
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update

from bot.models.base import async_session
from bot.models.promo_code import PromoActivation, PromoCode
from bot.models.user import User

logger = logging.getLogger(__name__)

_TYPE_ACTIONS = {
    "premium_7d": {"field": "premium", "days": 7},
    "premium_30d": {"field": "premium", "days": 30},
    "flac_5": {"field": "flac", "credits": 5},
}

PREMIUM_PROMO_TYPES = ("premium_7d", "premium_30d")


def generate_promo_code() -> str:
    return f"BR-{secrets.token_hex(4).upper()}"


async def create_promo(
    code: str,
    promo_type: str,
    max_uses: int,
    created_by: int,
    expires_days: int | None = None,
) -> PromoCode | None:
    expires_at = None
    if expires_days and expires_days > 0:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)
    async with async_session() as session:
        existing = await session.execute(select(PromoCode).where(PromoCode.code == code))
        if existing.scalar_one_or_none():
            return None
        promo = PromoCode(
            code=code,
            promo_type=promo_type,
            uses_left=max_uses,
            max_uses=max_uses,
            created_by=created_by,
            expires_at=expires_at,
        )
        session.add(promo)
        await session.commit()
        await session.refresh(promo)
        return promo


async def create_promo_auto(
    promo_type: str,
    max_uses: int,
    created_by: int,
    code: str | None = None,
    expires_days: int | None = None,
) -> PromoCode | None:
    """Create promo with optional explicit code or auto-generated unique code."""
    if code:
        return await create_promo(code.strip().upper(), promo_type, max_uses, created_by, expires_days)
    for _ in range(8):
        promo = await create_promo(generate_promo_code(), promo_type, max_uses, created_by, expires_days)
        if promo:
            return promo
    return None


async def list_promos() -> list[dict]:
    """List promos with activation counts and expiry info."""
    async with async_session() as session:
        result = await session.execute(
            select(PromoCode).order_by(PromoCode.created_at.desc()).limit(50)
        )
        promos = list(result.scalars().all())
        if not promos:
            return []

        counts_rows = await session.execute(
            select(PromoActivation.promo_id, func.count())
            .where(PromoActivation.promo_id.in_([p.id for p in promos]))
            .group_by(PromoActivation.promo_id)
        )
        counts = {pid: cnt for pid, cnt in counts_rows.all()}

        now = datetime.now(timezone.utc)
        items = []
        for p in promos:
            expired = bool(p.expires_at and p.expires_at < now)
            items.append({
                "code": p.code,
                "type": p.promo_type,
                "uses_left": p.uses_left,
                "max_uses": p.max_uses,
                "activations": int(counts.get(p.id, 0)),
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "expires_at": p.expires_at.isoformat() if p.expires_at else None,
                "expired": expired,
            })
        return items


async def activate_promo(code: str, user_id: int) -> tuple[bool, str]:
    """Activate a promo code for a user. Returns (success, message_key)."""
    code = code.strip().upper()
    if not code:
        return False, "promo_not_found"
    async with async_session() as session:
        result = await session.execute(select(PromoCode).where(PromoCode.code == code))
        promo = result.scalar_one_or_none()
        if not promo:
            return False, "promo_not_found"
        if promo.uses_left <= 0:
            return False, "promo_expired"
        if promo.expires_at and promo.expires_at < datetime.now(timezone.utc):
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
            db_user = await session.get(User, user_id)
            badges = (db_user.badges or []) if db_user else []
            if "premium" not in badges:
                badges = badges + ["premium"]
            await session.execute(
                update(User).where(User.id == user_id).values(
                    is_premium=True,
                    premium_until=premium_until,
                    badges=badges,
                )
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
