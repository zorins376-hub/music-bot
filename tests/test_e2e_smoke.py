"""
E2E smoke test — verifies the full /start → response flow through the Dispatcher.

Unlike unit tests that call handlers directly, this test feeds a real Update
object through the aiogram Dispatcher → router → handler chain, confirming
that routing, middlewares, and the handler all work together.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram import Bot, Dispatcher
from aiogram.types import Update


def _build_start_update() -> dict:
    """Raw Telegram-style Update dict for /start in a private chat."""
    return {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "date": 1700000000,
            "chat": {"id": 111, "type": "private", "first_name": "Test"},
            "from": {
                "id": 111,
                "is_bot": False,
                "first_name": "Test",
                "username": "testuser",
            },
            "text": "/start",
            "entities": [{"type": "bot_command", "offset": 0, "length": 6}],
        },
    }


def _make_db_user():
    u = MagicMock()
    u.id = 111
    u.username = "testuser"
    u.first_name = "Test"
    u.language = "ru"
    u.is_premium = False
    u.premium_until = None
    u.quality = "192"
    u.fav_genres = None
    u.fav_vibe = None
    u.fav_artists = None
    u.created_at = MagicMock(strftime=MagicMock(return_value="01.01.2025"))
    u.last_seen_version = "99.0.0"
    u.onboarded = True
    return u


class _FakeSession:
    """Intercepts all bot API calls and returns fake successful responses."""
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, bot, method, timeout=None):
        """Capture method name and return a minimal successful response."""
        method_name = method.__class__.__name__
        self.calls.append((method_name, {}))
        # Return a dict that aiogram can parse as the method's response
        # For SendMessage, Telegram returns the sent Message object
        from aiogram.types import Message as TgMessage, Chat as TgChat, User as TgUser
        return TgMessage(
            message_id=42,
            date=1700000000,
            chat=TgChat(id=111, type="private"),
            from_user=TgUser(id=999, is_bot=True, first_name="Bot"),
            text="ok",
        )

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_start_command_e2e():
    """Full dispatcher pipeline: Update → /start handler → bot.send_message."""
    from bot.handlers import start

    bot = Bot(token="1234567890:AAFakeTokenForTestingPurposesOnly000")
    fake_session = _FakeSession()
    bot.session = fake_session

    dp = Dispatcher()
    dp.include_router(start.router)

    db_user = _make_db_user()

    with patch("bot.handlers.start.get_or_create_user", new_callable=AsyncMock, return_value=db_user), \
         patch("bot.handlers.start.is_admin", return_value=False):
        raw = _build_start_update()
        update = Update.model_validate(raw, context={"bot": bot})
        await dp.feed_update(bot, update)

    # The handler used msg.answer() which delegates to bot.send_message
    # Our fake session should have captured at least one SendMessage call
    method_names = [name for name, _ in fake_session.calls]
    assert "SendMessage" in method_names, (
        f"Expected SendMessage in API calls, got: {method_names}"
    )
