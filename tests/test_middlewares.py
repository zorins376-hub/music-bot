"""
Тесты для middlewares: CaptchaMiddleware, ThrottleMiddleware.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call


# ─────────────────────────── ThrottleMiddleware ────────────────────────────

@pytest.mark.asyncio
class TestThrottleMiddleware:
    async def _make_event(self, user_id: int = 100, chat_type: str = "private", has_payment: bool = False):
        event = AsyncMock()
        event.from_user = MagicMock()
        event.from_user.id = user_id
        event.chat = MagicMock()
        event.chat.type = chat_type
        event.successful_payment = MagicMock() if has_payment else None
        return event

    async def test_first_message_passes(self, cache_with_fake_redis):
        from bot.middlewares.throttle import ThrottleMiddleware
        handler = AsyncMock(return_value="ok")
        middleware = ThrottleMiddleware()
        event = await self._make_event(200)

        with patch("bot.services.cache.cache", cache_with_fake_redis):
            result = await middleware(handler, event, {})

        handler.assert_called_once()

    async def test_second_message_blocked(self, cache_with_fake_redis):
        from bot.middlewares.throttle import ThrottleMiddleware
        handler = AsyncMock(return_value="ok")
        middleware = ThrottleMiddleware()
        event = await self._make_event(201)

        with patch("bot.services.cache.cache", cache_with_fake_redis):
            await middleware(handler, event, {})   # первый — проходит
            result = await middleware(handler, event, {})  # второй — блокируется

        assert handler.call_count == 1

    async def test_payment_bypasses_throttle(self, cache_with_fake_redis):
        """successful_payment не должен блокироваться throttle."""
        from bot.middlewares.throttle import ThrottleMiddleware
        handler = AsyncMock(return_value="ok")
        middleware = ThrottleMiddleware()

        event1 = await self._make_event(202, has_payment=False)
        event2 = await self._make_event(202, has_payment=True)  # оплата после flood

        with patch("bot.services.cache.cache", cache_with_fake_redis):
            await middleware(handler, event1, {})  # ставит ключ flood
            await middleware(handler, event2, {})  # должен пройти несмотря на flood

        assert handler.call_count == 2  # оба прошли

    async def test_no_user_passes_through(self, cache_with_fake_redis):
        from bot.middlewares.throttle import ThrottleMiddleware
        handler = AsyncMock()
        middleware = ThrottleMiddleware()
        event = AsyncMock()
        event.from_user = None
        event.successful_payment = None

        with patch("bot.services.cache.cache", cache_with_fake_redis):
            await middleware(handler, event, {})

        handler.assert_called_once()


# ─────────────────────────── CaptchaMiddleware ────────────────────────────

@pytest.mark.asyncio
class TestCaptchaMiddleware:
    def _make_private_event(self, user_id: int, text: str = "hello", captcha_passed: bool = False, has_payment: bool = False):
        event = AsyncMock()
        event.from_user = MagicMock()
        event.from_user.id = user_id
        event.chat = MagicMock()
        event.chat.type = "private"
        event.text = text
        event.successful_payment = MagicMock() if has_payment else None
        event.answer = AsyncMock()

        db_user = MagicMock()
        db_user.captcha_passed = captcha_passed
        db_user.language = "ru"

        return event, db_user

    async def test_verified_user_passes_through(self, cache_with_fake_redis):
        from bot.middlewares.captcha import CaptchaMiddleware
        handler = AsyncMock()
        middleware = CaptchaMiddleware()
        event, db_user = self._make_private_event(300, captcha_passed=True)

        with patch("bot.middlewares.captcha.get_or_create_user", new_callable=AsyncMock, return_value=db_user), \
             patch("bot.middlewares.captcha.cache", cache_with_fake_redis):
            await middleware(handler, event, {})

        handler.assert_called_once()

    async def test_payment_bypasses_captcha(self, cache_with_fake_redis):
        """Оплата должна проходить даже если капча не пройдена."""
        from bot.middlewares.captcha import CaptchaMiddleware
        handler = AsyncMock()
        middleware = CaptchaMiddleware()
        event, db_user = self._make_private_event(301, captcha_passed=False, has_payment=True)

        with patch("bot.middlewares.captcha.get_or_create_user", new_callable=AsyncMock, return_value=db_user), \
             patch("bot.middlewares.captcha.cache", cache_with_fake_redis):
            await middleware(handler, event, {})

        handler.assert_called_once()

    async def test_group_chat_skips_captcha(self, cache_with_fake_redis):
        """В группах капча не нужна."""
        from bot.middlewares.captcha import CaptchaMiddleware
        handler = AsyncMock()
        middleware = CaptchaMiddleware()
        event = AsyncMock()
        event.from_user = MagicMock()
        event.from_user.id = 302
        event.chat = MagicMock()
        event.chat.type = "group"
        event.text = "test"
        event.successful_payment = None

        db_user = MagicMock()
        db_user.captcha_passed = False
        db_user.language = "ru"

        with patch("bot.middlewares.captcha.get_or_create_user", new_callable=AsyncMock, return_value=db_user), \
             patch("bot.middlewares.captcha.cache", cache_with_fake_redis):
            await middleware(handler, event, {})

        handler.assert_called_once()

    async def test_unverified_user_gets_challenge(self, cache_with_fake_redis):
        """Непроверенный юзер получает капчу, хендлер не вызывается."""
        from bot.middlewares.captcha import CaptchaMiddleware
        handler = AsyncMock()
        middleware = CaptchaMiddleware()
        event, db_user = self._make_private_event(303, text="some music", captcha_passed=False)

        with patch("bot.middlewares.captcha.get_or_create_user", new_callable=AsyncMock, return_value=db_user), \
             patch("bot.middlewares.captcha.cache", cache_with_fake_redis), \
             patch("bot.middlewares.captcha._send_challenge", new_callable=AsyncMock):
            await middleware(handler, event, {})

        handler.assert_not_called()

    async def test_no_user_passes_through(self, cache_with_fake_redis):
        from bot.middlewares.captcha import CaptchaMiddleware
        handler = AsyncMock()
        middleware = CaptchaMiddleware()
        event = AsyncMock()
        event.from_user = None
        event.successful_payment = None

        with patch("bot.middlewares.captcha.cache", cache_with_fake_redis):
            await middleware(handler, event, {})

        handler.assert_called_once()
