"""
CAPTCHA middleware — simple math challenge for new users.

On first interaction the bot asks "a + b = ?" and blocks further
messages/callbacks until the user answers correctly.
Verified status is stored in Redis with a long TTL (30 days).
"""

import random
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from bot.db import get_or_create_user
from bot.i18n import t
from bot.services.cache import cache

_VERIFIED_TTL = 60 * 60 * 24 * 30  # 30 days
_CHALLENGE_TTL = 60 * 10            # 10 minutes to answer


def _verified_key(user_id: int) -> str:
    return f"captcha:ok:{user_id}"


def _challenge_key(user_id: int) -> str:
    return f"captcha:q:{user_id}"


class CaptchaMiddleware(BaseMiddleware):
    """Blocks messages from unverified users until they solve a captcha."""

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        user = event.from_user
        if user is None:
            return await handler(event, data)

        # Already verified?
        if await cache.redis.exists(_verified_key(user.id)):
            return await handler(event, data)

        # /start is always allowed (so the user can see the bot's greeting)
        if event.text and event.text.strip().startswith("/start"):
            # Generate captcha if not already pending
            if not await cache.redis.exists(_challenge_key(user.id)):
                await _send_challenge(event, user.id)
            return

        # Is there a pending challenge?
        answer = await cache.redis.get(_challenge_key(user.id))
        if answer is None:
            # No challenge yet — send one
            await _send_challenge(event, user.id)
            return

        # Check the user's answer
        text = (event.text or "").strip()
        if text == answer:
            await cache.redis.setex(_verified_key(user.id), _VERIFIED_TTL, "1")
            await cache.redis.delete(_challenge_key(user.id))
            db_user = await get_or_create_user(user)
            await event.answer(t(db_user.language, "captcha_ok"), parse_mode="HTML")
            # Don't pass the answer message to handlers (it's just a number)
            return
        else:
            db_user = await get_or_create_user(user)
            await event.answer(t(db_user.language, "captcha_fail"), parse_mode="HTML")
            return


async def _send_challenge(event: Message, user_id: int) -> None:
    a = random.randint(1, 20)
    b = random.randint(1, 20)
    answer = str(a + b)
    await cache.redis.setex(_challenge_key(user_id), _CHALLENGE_TTL, answer)
    db_user = await get_or_create_user(event.from_user)
    await event.answer(
        t(db_user.language, "captcha_prompt", a=a, b=b), parse_mode="HTML"
    )
