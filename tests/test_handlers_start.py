"""
Тесты для bot/handlers/start.py — /start, /help, /lang, /profile, main menu.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_user(uid=100, username="testuser", first_name="Test", lang="ru",
               is_premium=False, premium_until=None, quality="192",
               fav_genres=None, fav_vibe=None, fav_artists=None):
    u = MagicMock()
    u.id = uid
    u.username = username
    u.first_name = first_name
    u.language = lang
    u.is_premium = is_premium
    u.premium_until = premium_until
    u.quality = quality
    u.fav_genres = fav_genres
    u.fav_vibe = fav_vibe
    u.fav_artists = fav_artists
    u.created_at = MagicMock(strftime=MagicMock(return_value="01.01.2025"))
    u.last_seen_version = "99.0.0"
    u.onboarded = True
    return u


class TestMainMenu:
    def test_main_menu_regular(self):
        from bot.handlers.start import _main_menu
        kb = _main_menu("ru", admin=False)
        # Не должно быть кнопки "Админ-панель"
        all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "◆ Админ-панель" not in all_texts
        assert "◈ Найти трек" in all_texts
        assert "◇ Premium" in all_texts

    def test_main_menu_admin(self):
        from bot.handlers.start import _main_menu
        kb = _main_menu("ru", admin=True)
        all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "◆ Админ-панель" in all_texts

    def test_main_menu_has_radio_buttons(self):
        from bot.handlers.start import _main_menu
        kb = _main_menu("ru")
        all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "▸ TEQUILA LIVE" in all_texts
        assert "◑ FULLMOON LIVE" in all_texts
        assert "✦ AUTO MIX" in all_texts


@pytest.mark.asyncio
class TestCmdStart:
    async def test_sends_welcome_message(self):
        from bot.handlers.start import cmd_start

        user = _make_user()
        msg = AsyncMock()
        msg.from_user = MagicMock(id=100, username="test", first_name="Test")
        msg.text = "/start"
        msg.answer = AsyncMock()

        with patch("bot.handlers.start.get_or_create_user", new_callable=AsyncMock, return_value=user), \
             patch("bot.handlers.start.is_admin", return_value=False):
            await cmd_start(msg)

        assert msg.answer.call_count >= 1
        # First call is the main menu
        args, kwargs = msg.answer.call_args_list[0]
        assert kwargs.get("reply_markup") is not None
        assert kwargs.get("parse_mode") == "HTML"


@pytest.mark.asyncio
class TestCmdHelp:
    async def test_sends_help(self):
        from bot.handlers.start import cmd_help

        user = _make_user()
        msg = AsyncMock()
        msg.from_user = MagicMock(id=100, username="test", first_name="Test")
        msg.answer = AsyncMock()

        with patch("bot.handlers.start.get_or_create_user", new_callable=AsyncMock, return_value=user):
            await cmd_help(msg)

        msg.answer.assert_called_once()


@pytest.mark.asyncio
class TestCmdLang:
    async def test_shows_language_keyboard(self):
        from bot.handlers.start import cmd_lang

        user = _make_user()
        msg = AsyncMock()
        msg.from_user = MagicMock(id=100, username="test", first_name="Test")
        msg.answer = AsyncMock()

        with patch("bot.handlers.start.get_or_create_user", new_callable=AsyncMock, return_value=user):
            await cmd_lang(msg)

        msg.answer.assert_called_once()
        _, kwargs = msg.answer.call_args
        assert kwargs.get("reply_markup") is not None


@pytest.mark.asyncio
class TestHandleLangChange:
    async def test_changes_language(self):
        from bot.handlers.start import handle_lang_change

        cb = AsyncMock()
        cb.data = "lang:en"
        cb.from_user = MagicMock(id=100)
        cb.answer = AsyncMock()
        cb.message = AsyncMock()
        cb.message.edit_text = AsyncMock()

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("bot.handlers.start.async_session", return_value=mock_session):
            await handle_lang_change(cb)

        mock_session.execute.assert_called_once()
        cb.message.edit_text.assert_called_once()

    async def test_rejects_invalid_lang(self):
        from bot.handlers.start import handle_lang_change

        cb = AsyncMock()
        cb.data = "lang:xx"
        cb.from_user = MagicMock(id=100)
        cb.answer = AsyncMock()
        cb.message = AsyncMock()

        await handle_lang_change(cb)
        cb.answer.assert_called_once()


@pytest.mark.asyncio
class TestHandleSearchButton:
    async def test_prompts_search(self):
        from bot.handlers.start import handle_search_button

        user = _make_user()
        cb = AsyncMock()
        cb.from_user = MagicMock(id=100, username="test", first_name="Test")
        cb.answer = AsyncMock()
        cb.message = AsyncMock()
        cb.message.answer = AsyncMock()

        with patch("bot.handlers.start.get_or_create_user", new_callable=AsyncMock, return_value=user):
            await handle_search_button(cb)

        cb.answer.assert_called_once()
        cb.message.answer.assert_called_once()
