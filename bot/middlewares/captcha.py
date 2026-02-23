"""
CAPTCHA middleware — simple math challenge for new users.

On first interaction the bot asks "a + b = ?" and blocks further
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
        tg_user = event.from_user
        if tg_user is None:
            return await handler(event, data)

        db_user = await get_or_create_user(tg_user)

        # Already verified — pass through forever
        if db_user.captcha_passed:
            return await handler(event, data)

        # /start is always allowed
        if event.text and event.text.strip().startswith("/start"):
            if not await cache.redis.exists(_challenge_key(tg_user.id)):
                await _send_challenge(event, tg_user.id, db_user.language)
            return

        # Is there a pending challenge?
        answer = await cache.redis.get(_challenge_key(tg_user.id))
        if answer is None:
            await _send_challenge(event, tg_user.id, db_user.language)
            return

        # Check the user's answer
        text = (event.text or "").strip()
        if text == answer:
            # Mark as passed permanently in DB
            async with async_session() as session:
                await session.execute(
                    update(User).where(User.id == tg_user.id).values(captcha_passed=True)
                )
                await session.commit()
            await cache.redis.delete(_challenge_key(tg_user.id))
            await event.answer(t(db_user.language, "captcha_ok"), parse_mode="HTML")
            return
        else:
            await event.answer(t(db_user.language, "captcha_fail"), parse_mode="HTML")
            return


async def _send_challenge(event: Message, user_id: int, lang: str) -> None:
    a = random.randint(1, 20)
    b = random.randint(1, 20)
    answer = str(a + b)
    await cache.redis.setex(_challenge_key(user_id), _CHALLENGE_TTL, answer)
    await event.answer(
        t(lang, "captcha_prompt", a=a, b=b), parse_mode="HTML"
    )
