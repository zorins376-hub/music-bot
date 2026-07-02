"""
premium_scheduler.py — Premium lifecycle background tasks.

- Auto-expire: revoke is_premium for users whose premium_until has passed
  (so stats stay accurate even if the user never returns) and notify them once.
- Expiry reminder: DM users whose premium expires within the next 2 days,
  with a "renew" button. Each user is reminded at most once per cycle window.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select, update

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_SEC = 3600  # hourly
_REMIND_WINDOW_DAYS = 2
_REMIND_FLAG_TTL = 3 * 24 * 3600  # don't re-remind within 3 days
_EXPIRE_FLAG_TTL = 7 * 24 * 3600


def _renew_keyboard(lang: str) -> InlineKeyboardMarkup:
    from bot.i18n import t
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t(lang, "premium_renew_btn"), callback_data="action:premium"),
    ]])


async def start_premium_scheduler(bot) -> None:
    """Start the premium lifecycle loop. Call from on_startup."""
    asyncio.create_task(_premium_loop(bot))


async def _premium_loop(bot) -> None:
    # small initial delay so startup isn't blocked
    await asyncio.sleep(60)
    while True:
        try:
            await _remind_expiring_soon(bot)
            await _expire_overdue(bot)
        except Exception:
            logger.warning("premium scheduler cycle failed", exc_info=True)
        await asyncio.sleep(_CHECK_INTERVAL_SEC)


async def _redis_set_once(key: str, ttl: int) -> bool:
    """Return True if this is the first time the flag is set (NX)."""
    try:
        from bot.services.cache import cache
        ok = await cache.redis.set(key, "1", ex=ttl, nx=True)
        return bool(ok)
    except Exception:
        logger.debug("premium scheduler redis flag failed: %s", key, exc_info=True)
        # If redis is unavailable, fall back to allowing the action (better to
        # notify than to silently drop), but avoid raising.
        return True


async def _remind_expiring_soon(bot) -> None:
    from bot.config import settings
    from bot.i18n import t
    from bot.models.base import async_session
    from bot.models.user import User

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=_REMIND_WINDOW_DAYS)
    admin_ids = set(settings.ADMIN_IDS or [])

    async with async_session() as session:
        result = await session.execute(
            select(User).where(
                User.is_premium == True,  # noqa: E712
                User.premium_until.is_not(None),
                User.premium_until > now,
                User.premium_until <= horizon,
            )
        )
        users = list(result.scalars().all())

    for user in users:
        if user.id in admin_ids:
            continue
        flag = f"premium:remind_expiry:{user.id}"
        if not await _redis_set_once(flag, _REMIND_FLAG_TTL):
            continue
        lang = user.language or "ru"
        until = user.premium_until.strftime("%d.%m.%Y") if user.premium_until else ""
        try:
            await bot.send_message(
                user.id,
                t(lang, "premium_expiring_soon", until=until),
                reply_markup=_renew_keyboard(lang),
                parse_mode="HTML",
            )
        except Exception:
            logger.debug("could not remind user %s about expiry", user.id, exc_info=True)


async def _expire_overdue(bot) -> None:
    from bot.config import settings
    from bot.i18n import t
    from bot.models.base import async_session
    from bot.models.user import User

    now = datetime.now(timezone.utc)
    admin_ids = set(settings.ADMIN_IDS or [])

    async with async_session() as session:
        result = await session.execute(
            select(User).where(
                User.is_premium == True,  # noqa: E712
                User.premium_until.is_not(None),
                User.premium_until < now,
            )
        )
        users = list(result.scalars().all())

        ids_to_expire = [u.id for u in users if u.id not in admin_ids]
        if ids_to_expire:
            await session.execute(
                update(User).where(User.id.in_(ids_to_expire)).values(is_premium=False)
            )
            await session.commit()

    for user in users:
        if user.id in admin_ids:
            continue
        flag = f"premium:expired_notice:{user.id}"
        if not await _redis_set_once(flag, _EXPIRE_FLAG_TTL):
            continue
        lang = user.language or "ru"
        try:
            await bot.send_message(
                user.id,
                t(lang, "premium_expired_notice"),
                reply_markup=_renew_keyboard(lang),
                parse_mode="HTML",
            )
        except Exception:
            logger.debug("could not notify user %s about expiry", user.id, exc_info=True)

    if ids_to_expire:
        logger.info("Premium auto-expired for %d users", len(ids_to_expire))
