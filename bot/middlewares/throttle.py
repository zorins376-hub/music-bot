from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message

# Защита от флуда: 1 сообщение в секунду на пользователя
_FLOOD_WINDOW = 1  # секунды


class ThrottleMiddleware(BaseMiddleware):
    """Базовая anti-flood защита. Rate limiting по трекам — в search.py."""

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        from bot.services.cache import cache

        user = event.from_user
        if user is None:
            return await handler(event, data)

        flood_key = f"flood:{user.id}"
        if await cache.redis.exists(flood_key):
            # Молча игнорируем — не засоряем чат сообщениями об ошибке
            return

        await cache.redis.setex(flood_key, _FLOOD_WINDOW, "1")
        return await handler(event, data)
