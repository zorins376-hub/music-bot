import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message

logger = logging.getLogger("bot.requests")


class LoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        user = event.from_user
        text = event.text or event.caption or ""
        logger.info(
            "user_id=%s username=%s text=%r",
            user.id if user else "?",
            user.username if user else "?",
            text[:100],
        )
        return await handler(event, data)
