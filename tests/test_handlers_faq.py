"""
Тесты для bot/handlers/faq.py — FAQ раздел.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_user(lang="ru"):
    u = MagicMock()
    u.language = lang
    return u


class TestFaqKeyboard:
    def test_keyboard_has_sections(self):
        from bot.handlers.faq import _faq_keyboard
        kb = _faq_keyboard("ru")
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert any("faq:search" in d for d in all_data)
        assert any("faq:premium" in d for d in all_data)
        assert any("faq:commands" in d for d in all_data)


class TestBackButton:
    def test_back_button(self):
        from bot.handlers.faq import _back_button
        kb = _back_button("ru")
        assert len(kb.inline_keyboard) == 1
        assert kb.inline_keyboard[0][0].callback_data == "faq:back"


@pytest.mark.asyncio
class TestCmdFaq:
    async def test_shows_faq(self):
        from bot.handlers.faq import cmd_faq
        user = _make_user()
        msg = AsyncMock()
        msg.from_user = MagicMock(id=100, username="t", first_name="T")
        msg.answer = AsyncMock()

        with patch("bot.handlers.faq.get_or_create_user", new_callable=AsyncMock, return_value=user):
            await cmd_faq(msg)

        msg.answer.assert_called_once()
        _, kwargs = msg.answer.call_args
        assert kwargs.get("reply_markup") is not None
        assert kwargs.get("parse_mode") == "HTML"


@pytest.mark.asyncio
class TestHandleFaq:
    async def test_back_returns_to_main(self):
        from bot.handlers.faq import handle_faq
        user = _make_user()
        cb = AsyncMock()
        cb.data = "faq:back"
        cb.from_user = MagicMock(id=100, username="t", first_name="T")
        cb.answer = AsyncMock()
        cb.message = AsyncMock()
        cb.message.edit_text = AsyncMock()

        with patch("bot.handlers.faq.get_or_create_user", new_callable=AsyncMock, return_value=user):
            await handle_faq(cb)

        cb.answer.assert_called_once()
        cb.message.edit_text.assert_called_once()

    async def test_section_shows_content(self):
        from bot.handlers.faq import handle_faq
        user = _make_user()
        cb = AsyncMock()
        cb.data = "faq:search"
        cb.from_user = MagicMock(id=100, username="t", first_name="T")
        cb.answer = AsyncMock()
        cb.message = AsyncMock()
        cb.message.edit_text = AsyncMock()

        with patch("bot.handlers.faq.get_or_create_user", new_callable=AsyncMock, return_value=user):
            await handle_faq(cb)

        cb.message.edit_text.assert_called_once()
        args, kwargs = cb.message.edit_text.call_args
        assert kwargs.get("parse_mode") == "HTML"


@pytest.mark.asyncio
class TestSendFaq:
    async def test_send_faq_function(self):
        from bot.handlers.faq import send_faq
        msg = AsyncMock()
        msg.answer = AsyncMock()

        await send_faq(msg, "ru")
        msg.answer.assert_called_once()
