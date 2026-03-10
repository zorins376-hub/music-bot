"""
Тесты для bot/handlers/settings.py — настройки качества аудио.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_user(uid=100, quality="192", is_premium=False, lang="ru"):
    u = MagicMock()
    u.id = uid
    u.quality = quality
    u.is_premium = is_premium
    u.language = lang
    u.release_radar_enabled = True
    u.fav_vibe = None
    return u


class TestQualityKeyboard:
    def test_regular_user_no_320(self):
        from bot.handlers.settings import _quality_keyboard
        kb = _quality_keyboard(is_premium=False, current="192")
        all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        # 320 should be disabled for non-premium
        assert any("320" in t and "Premium" in t for t in all_texts)

    def test_premium_user_has_320(self):
        from bot.handlers.settings import _quality_keyboard
        kb = _quality_keyboard(is_premium=True, current="192")
        all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("320" in t for t in all_texts)
        # Should not have "Premium" lock text
        assert not any("Premium)" in t for t in all_texts)

    def test_checkmark_on_current(self):
        from bot.handlers.settings import _quality_keyboard
        kb = _quality_keyboard(is_premium=True, current="192")
        all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("✓" in t and "192" in t for t in all_texts)
        # Others without checkmark
        assert any("128" in t and "✓" not in t for t in all_texts)

    def test_auto_option_present(self):
        from bot.handlers.settings import _quality_keyboard
        kb = _quality_keyboard(is_premium=False, current="192")
        all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("Auto" in t for t in all_texts)


@pytest.mark.asyncio
class TestCmdSettings:
    async def test_shows_settings(self):
        from bot.handlers.settings import cmd_settings
        user = _make_user()
        msg = AsyncMock()
        msg.from_user = MagicMock(id=100, username="t", first_name="T")
        msg.answer = AsyncMock()

        with patch("bot.handlers.settings.get_or_create_user", new_callable=AsyncMock, return_value=user):
            await cmd_settings(msg)

        msg.answer.assert_called_once()
        _, kwargs = msg.answer.call_args
        assert kwargs.get("reply_markup") is not None

    async def test_settings_releases_off_command(self):
        from bot.handlers.settings import cmd_settings
        user = _make_user()
        msg = AsyncMock()
        msg.from_user = MagicMock(id=100, username="t", first_name="T")
        msg.text = "/settings releases off"
        msg.answer = AsyncMock()

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("bot.handlers.settings.get_or_create_user", new_callable=AsyncMock, return_value=user), \
             patch("bot.handlers.settings.async_session", return_value=mock_session):
            await cmd_settings(msg)

        mock_session.execute.assert_called_once()
        msg.answer.assert_called_once()


@pytest.mark.asyncio
class TestHandleQualityChange:
    async def test_change_to_128(self):
        from bot.handlers.settings import handle_quality_change

        user = _make_user(quality="192", is_premium=False)
        cb = AsyncMock()
        cb.data = "quality:128"
        cb.from_user = MagicMock(id=100)
        cb.answer = AsyncMock()
        cb.message = AsyncMock()
        cb.message.edit_text = AsyncMock()

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("bot.handlers.settings.get_or_create_user", new_callable=AsyncMock, return_value=user), \
             patch("bot.handlers.settings.async_session", return_value=mock_session):
            await handle_quality_change(cb)

        mock_session.execute.assert_called_once()
        cb.message.edit_text.assert_called_once()

    async def test_320_blocked_for_free_user(self):
        from bot.handlers.settings import handle_quality_change

        user = _make_user(is_premium=False)
        cb = AsyncMock()
        cb.data = "quality:320"
        cb.from_user = MagicMock(id=100)
        cb.answer = AsyncMock()
        cb.message = AsyncMock()

        with patch("bot.handlers.settings.get_or_create_user", new_callable=AsyncMock, return_value=user):
            await handle_quality_change(cb)

        cb.answer.assert_called_once()
        _, kwargs = cb.answer.call_args
        assert kwargs.get("show_alert") is True

    async def test_320_allowed_for_premium_user(self):
        from bot.handlers.settings import handle_quality_change

        user = _make_user(is_premium=True)
        cb = AsyncMock()
        cb.data = "quality:320"
        cb.from_user = MagicMock(id=100)
        cb.answer = AsyncMock()
        cb.message = AsyncMock()
        cb.message.edit_text = AsyncMock()

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("bot.handlers.settings.get_or_create_user", new_callable=AsyncMock, return_value=user), \
             patch("bot.handlers.settings.async_session", return_value=mock_session):
            await handle_quality_change(cb)

        mock_session.execute.assert_called_once()
        cb.message.edit_text.assert_called_once()

    async def test_invalid_quality_rejected(self):
        from bot.handlers.settings import handle_quality_change

        cb = AsyncMock()
        cb.data = "quality:999"
        cb.from_user = MagicMock(id=100)
        cb.answer = AsyncMock()

        await handle_quality_change(cb)
        cb.answer.assert_called_once()

    async def test_auto_quality_allowed_for_free_user(self):
        from bot.handlers.settings import handle_quality_change

        user = _make_user(is_premium=False)
        cb = AsyncMock()
        cb.data = "quality:auto"
        cb.from_user = MagicMock(id=100)
        cb.answer = AsyncMock()
        cb.message = AsyncMock()
        cb.message.edit_text = AsyncMock()

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("bot.handlers.settings.get_or_create_user", new_callable=AsyncMock, return_value=user), \
             patch("bot.handlers.settings.async_session", return_value=mock_session):
            await handle_quality_change(cb)

        mock_session.execute.assert_called_once()
        cb.message.edit_text.assert_called_once()


@pytest.mark.asyncio
class TestReleaseRadarSettingsToggle:
    async def test_callback_toggle_releases(self):
        from bot.handlers.settings import handle_releases_toggle

        user = _make_user()
        user.release_radar_enabled = True
        cb = AsyncMock()
        cb.data = "settings:releases"
        cb.from_user = MagicMock(id=100)
        cb.answer = AsyncMock()
        cb.message = AsyncMock()
        cb.message.edit_reply_markup = AsyncMock()

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("bot.handlers.settings.get_or_create_user", new_callable=AsyncMock, return_value=user), \
             patch("bot.handlers.settings.async_session", return_value=mock_session):
            await handle_releases_toggle(cb)

        cb.answer.assert_called_once()
        mock_session.execute.assert_called_once()
        cb.message.edit_reply_markup.assert_called_once()
