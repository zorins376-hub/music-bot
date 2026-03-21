"""
CAPTCHA middleware — math challenge for new users.

On first interaction the bot asks "a × b + c = ?" and blocks further
messages/callbacks until the user answers correctly.
Verified status is stored in the database permanently.
"""

import logging
import random
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message
from sqlalchemy import update

logger = logging.getLogger(__name__)

from bot.db import get_or_create_user
from bot.i18n import t
from bot.models.base import async_session
from bot.models.user import User
from bot.services.cache import cache
from bot.version import WELCOME_MESSAGE

_CHALLENGE_TTL = 60 * 10  # 10 minutes to answer
_MAX_ATTEMPTS = 5          # max wrong answers before cooldown
_BLOCK_TTLS = [60 * 10, 60 * 30, 60 * 60 * 24]  # escalating: 10m, 30m, 24h


def _challenge_key(user_id: int) -> str:
    return f"captcha:q:{user_id}"


def _fails_key(user_id: int) -> str:
    return f"captcha:fails:{user_id}"


def _block_key(user_id: int) -> str:
    return f"captcha:block:{user_id}"


def _block_count_key(user_id: int) -> str:
    return f"captcha:blockcnt:{user_id}"


class CaptchaMiddleware(BaseMiddleware):
    """Blocks messages from unverified users until they solve a captcha."""

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        tg_user = event.from_user
        if tg_user is None:
            return await handler(event, data)

        # Skip captcha in group chats — only require in private DM
        if event.chat.type != "private":
            return await handler(event, data)

        try:
            db_user = await get_or_create_user(tg_user)
        except Exception:
            # DB temporarily unavailable — let the request through
            return await handler(event, data)

        # Already verified — pass through forever
        if db_user.captcha_passed:
            return await handler(event, data)

        # /start и successful_payment всегда пропускаем
        if event.text and event.text.strip().startswith("/start"):
            try:
                if not await cache.redis.exists(_challenge_key(tg_user.id)):
                    await _send_challenge(event, tg_user.id, db_user.language)
            except Exception:
                logger.debug("captcha start check failed user=%s", tg_user.id, exc_info=True)
            return

        # Платёж нельзя блокировать — деньги уже списаны
        if event.successful_payment is not None:
            return await handler(event, data)

        # Check if user is blocked for too many failures
        try:
            if await cache.redis.exists(_block_key(tg_user.id)):
                block_ttl = await cache.redis.ttl(_block_key(tg_user.id))
                mins = max(1, block_ttl // 60)
                await event.answer(
                    t(db_user.language, "captcha_blocked", minutes=mins),
                    parse_mode="HTML",
                )
                return
        except Exception:
            logger.debug("captcha block check failed user=%s", tg_user.id, exc_info=True)

        # Is there a pending challenge?
        try:
            answer = await cache.redis.get(_challenge_key(tg_user.id))
        except Exception:
            # Redis unavailable → skip captcha, let through
            return await handler(event, data)

        if answer is None:
            await _send_challenge(event, tg_user.id, db_user.language)
            return

        # Check the user's answer
        text = (event.text or "").strip()
        if text == answer:
            # Mark as passed permanently in DB
            try:
                async with async_session() as session:
                    await session.execute(
                        update(User).where(User.id == tg_user.id).values(captcha_passed=True, welcome_sent=True)
                    )
                    await session.commit()
            except Exception:
                logger.debug("captcha pass DB update failed user=%s", tg_user.id, exc_info=True)
            try:
                await cache.redis.delete(_challenge_key(tg_user.id))
                await cache.redis.delete(_fails_key(tg_user.id))
            except Exception:
                logger.debug("captcha redis cleanup failed user=%s", tg_user.id, exc_info=True)
            await event.answer(t(db_user.language, "captcha_ok"), parse_mode="HTML")
            # Send welcome message to new users
            await event.answer(WELCOME_MESSAGE, parse_mode="HTML")
            return
        else:
            # Track failed attempts
            try:
                fails = await cache.redis.incr(_fails_key(tg_user.id))
                if fails == 1:
                    await cache.redis.expire(_fails_key(tg_user.id), _CHALLENGE_TTL)
                if fails >= _MAX_ATTEMPTS:
                    # Escalating block: 10m → 30m → 24h
                    block_cnt = int(await cache.redis.get(_block_count_key(tg_user.id)) or 0)
                    block_ttl = _BLOCK_TTLS[min(block_cnt, len(_BLOCK_TTLS) - 1)]
                    await cache.redis.setex(_block_key(tg_user.id), block_ttl, "1")
                    await cache.redis.set(_block_count_key(tg_user.id), str(block_cnt + 1))
                    await cache.redis.expire(_block_count_key(tg_user.id), 60 * 60 * 48)  # reset after 48h
                    await cache.redis.delete(_challenge_key(tg_user.id))
                    await cache.redis.delete(_fails_key(tg_user.id))
                    await event.answer(
                        t(db_user.language, "captcha_blocked", minutes=block_ttl // 60),
                        parse_mode="HTML",
                    )
                    return
            except Exception:
                logger.debug("captcha fail tracking failed user=%s", tg_user.id, exc_info=True)
            await event.answer(t(db_user.language, "captcha_fail"), parse_mode="HTML")
            return


async def _send_challenge(event: Message, user_id: int, lang: str) -> None:
    a = random.randint(1, 9)
    b = random.randint(1, 9)
    c = random.randint(1, 9)
    answer = str(a * b + c)
    try:
        await cache.redis.setex(_challenge_key(user_id), _CHALLENGE_TTL, answer)
        await cache.redis.delete(_fails_key(user_id))
    except Exception:
        logger.debug("captcha challenge redis set failed user=%s", user_id, exc_info=True)
    await event.answer(
        t(lang, "captcha_prompt", a=a, b=b, c=c), parse_mode="HTML"
    )
