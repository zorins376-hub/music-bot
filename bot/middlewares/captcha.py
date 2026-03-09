"""
CAPTCHA middleware — math challenge for new users.

On first interaction the bot asks "a × b + c = ?" and blocks further
messages/callbacks until the user answers correctly.
Verified status is stored in the database permanently.
"""

import random
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message
from sqlalchemy import update

from bot.db import get_or_create_user
from bot.i18n import t
from bot.models.base import async_session
from bot.models.user import User
from bot.services.cache import cache

_CHALLENGE_TTL = 60 * 10  # 10 minutes to answer
_MAX_ATTEMPTS = 5          # max wrong answers before cooldown
_BLOCK_TTL = 60 * 10      # 10 min block after too many failures


def _challenge_key(user_id: int) -> str:
    return f"captcha:q:{user_id}"


def _fails_key(user_id: int) -> str:
    return f"captcha:fails:{user_id}"


def _block_key(user_id: int) -> str:
    return f"captcha:block:{user_id}"


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
                pass
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
            pass

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
                        update(User).where(User.id == tg_user.id).values(captcha_passed=True)
                    )
                    await session.commit()
            except Exception:
                pass
            try:
                await cache.redis.delete(_challenge_key(tg_user.id))
                await cache.redis.delete(_fails_key(tg_user.id))
            except Exception:
                pass
            await event.answer(t(db_user.language, "captcha_ok"), parse_mode="HTML")
            return
        else:
            # Track failed attempts
            try:
                fails = await cache.redis.incr(_fails_key(tg_user.id))
                if fails == 1:
                    await cache.redis.expire(_fails_key(tg_user.id), _CHALLENGE_TTL)
                if fails >= _MAX_ATTEMPTS:
                    await cache.redis.setex(_block_key(tg_user.id), _BLOCK_TTL, "1")
                    await cache.redis.delete(_challenge_key(tg_user.id))
                    await cache.redis.delete(_fails_key(tg_user.id))
                    await event.answer(
                        t(db_user.language, "captcha_blocked", minutes=_BLOCK_TTL // 60),
                        parse_mode="HTML",
                    )
                    return
            except Exception:
                pass
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
        pass
    await event.answer(
        t(lang, "captcha_prompt", a=a, b=b, c=c), parse_mode="HTML"
    )
