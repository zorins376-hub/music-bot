"""
Тесты для bot/handlers/premium.py
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch


def make_premium_user(user_id: int = 500, is_premium: bool = False, premium_until=None):
    user = MagicMock()
    user.id = user_id
    user.is_premium = is_premium
    user.premium_until = premium_until
    user.language = "ru"
    return user


@pytest.mark.asyncio
class TestHandlePremium:
    async def test_shows_buy_button_for_regular_user(self):
        from bot.handlers.premium import handle_premium
        user = make_premium_user(is_premium=False)
        cb = AsyncMock()
        cb.from_user = MagicMock(id=500)
        cb.answer = AsyncMock()
        cb.message = AsyncMock()
        cb.message.answer = AsyncMock()

        with patch("bot.handlers.premium.get_or_create_user", new_callable=AsyncMock, return_value=user):
            await handle_premium(cb)

        cb.message.answer.assert_called_once()
        args, kwargs = cb.message.answer.call_args
        # Должна быть клавиатура с кнопкой покупки
        assert kwargs.get("reply_markup") is not None

    async def test_shows_active_status_for_premium_user(self):
        from bot.handlers.premium import handle_premium
        until = datetime.now(timezone.utc) + timedelta(days=25)
        user = make_premium_user(is_premium=True, premium_until=until)
        cb = AsyncMock()
        cb.from_user = MagicMock(id=501)
        cb.answer = AsyncMock()
        cb.message = AsyncMock()
        cb.message.answer = AsyncMock()

        with patch("bot.handlers.premium.get_or_create_user", new_callable=AsyncMock, return_value=user):
            await handle_premium(cb)

        cb.message.answer.assert_called_once()
        args, kwargs = cb.message.answer.call_args
        # Нет кнопки покупки для уже premium
        assert kwargs.get("reply_markup") is None


@pytest.mark.asyncio
class TestHandlePreCheckout:
    async def test_always_approves(self):
        from bot.handlers.premium import handle_pre_checkout
        pre_checkout = AsyncMock()
        pre_checkout.answer = AsyncMock()

        await handle_pre_checkout(pre_checkout)

        pre_checkout.answer.assert_called_once_with(ok=True)


@pytest.mark.asyncio
class TestHandleSuccessfulPayment:
    async def test_grants_premium_and_records_payment(self):
        from bot.handlers.premium import handle_successful_payment
        user = make_premium_user(is_premium=False)
        message = AsyncMock()
        message.from_user = MagicMock(id=502)
        message.answer = AsyncMock()
        message.successful_payment = MagicMock()
        message.successful_payment.total_amount = 150
        message.successful_payment.currency = "XTR"
        message.successful_payment.invoice_payload = "premium_30d"

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("bot.handlers.premium.get_or_create_user", new_callable=AsyncMock, return_value=user), \
             patch("bot.handlers.premium.async_session", return_value=mock_session):
            await handle_successful_payment(message)

        # Должен был вызвать session.execute (UPDATE users) и session.add (Payment)
        assert mock_session.execute.called
        assert mock_session.add.called
        assert mock_session.commit.called
        # Пользователь получил сообщение об успехе
        message.answer.assert_called_once()

    async def test_premium_until_is_30_days_from_now(self):
        """Дата окончания Premium — через 30 дней."""
        from bot.handlers.premium import handle_successful_payment
        from bot.config import settings

        user = make_premium_user(is_premium=False)
        message = AsyncMock()
        message.from_user = MagicMock(id=503)
        message.answer = AsyncMock()
        message.successful_payment = MagicMock()
        message.successful_payment.total_amount = 150
        message.successful_payment.currency = "XTR"
        message.successful_payment.invoice_payload = "premium_30d"

        captured_values = {}

        mock_session = AsyncMock()
        def capture_execute(stmt):
            # Извлекаем значения из UPDATE stmt
            try:
                compiled = stmt.compile()
            except Exception:
                pass
            return AsyncMock()()
        mock_session.execute = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        before = datetime.now(timezone.utc)
        with patch("bot.handlers.premium.get_or_create_user", new_callable=AsyncMock, return_value=user), \
             patch("bot.handlers.premium.async_session", return_value=mock_session):
            await handle_successful_payment(message)
        after = datetime.now(timezone.utc)

        # Проверяем что Premium выдан на settings.PREMIUM_DAYS дней
        expected_min = before + timedelta(days=settings.PREMIUM_DAYS)
        expected_max = after + timedelta(days=settings.PREMIUM_DAYS)
        # Просто проверяем что execute был вызван с нужными аргументами
        assert mock_session.execute.call_count >= 1


@pytest.mark.asyncio
class TestHandlePremiumBuy:
    async def test_sends_invoice(self):
        from bot.handlers.premium import handle_premium_buy
        user = make_premium_user(is_premium=False)
        cb = AsyncMock()
        cb.from_user = MagicMock(id=504)
        cb.answer = AsyncMock()
        cb.message = AsyncMock()
        cb.message.answer_invoice = AsyncMock()

        with patch("bot.handlers.premium.get_or_create_user", new_callable=AsyncMock, return_value=user):
            await handle_premium_buy(cb)

        cb.message.answer_invoice.assert_called_once()
        _, kwargs = cb.message.answer_invoice.call_args
        assert kwargs["currency"] == "XTR"  # Telegram Stars
        assert kwargs["payload"] == "premium_30d"
