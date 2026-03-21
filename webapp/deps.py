"""Shared dependencies used across webapp route modules."""
import asyncio
import logging

from fastapi import Header, HTTPException

from webapp.auth import verify_init_data

logger = logging.getLogger(__name__)

# Strong references to background tasks to prevent GC before completion
_background_tasks: set[asyncio.Task] = set()


def _fire_task(coro) -> asyncio.Task:
    """Create a background task with GC protection."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)

    def _on_done(done: asyncio.Task) -> None:
        _background_tasks.discard(done)
        if done.cancelled():
            return
        exc = done.exception()
        if exc:
            logger.error("Background task failed: %s", exc, exc_info=exc)

    task.add_done_callback(_on_done)
    return task


async def get_current_user(x_telegram_init_data: str = Header(...)) -> dict:
    """Extract and verify Telegram user from initData header."""
    user = verify_init_data(x_telegram_init_data)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid initData")
    return user


async def _get_redis():
    from bot.services.cache import cache
    return cache.redis


async def _get_or_create_webapp_user(tg_user: dict):
    from bot.db import get_or_create_user_raw

    user_id = int(tg_user["id"])
    username = tg_user.get("username")
    first_name = tg_user.get("first_name") or ""
    return await get_or_create_user_raw(user_id, username, first_name)
