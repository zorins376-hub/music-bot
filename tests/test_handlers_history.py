"""
Тесты для bot/handlers/history.py — /history, /top, /stats.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_user(uid=100, lang="ru"):
    u = MagicMock()
    u.id = uid
    u.language = lang
    u.created_at = MagicMock(strftime=MagicMock(return_value="01.01.2025"))
    return u


@pytest.mark.asyncio
class TestCmdHistory:
    async def test_empty_history(self):
        from bot.handlers.history import cmd_history

        user = _make_user()
        msg = AsyncMock()
        msg.from_user = MagicMock(id=100, username="t", first_name="T")
        msg.answer = AsyncMock()

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("bot.handlers.history.get_or_create_user", new_callable=AsyncMock, return_value=user), \
             patch("bot.handlers.history.async_session", return_value=mock_session):
            await cmd_history(msg)

        msg.answer.assert_called_once()

    async def test_history_with_entries(self):
        from bot.handlers.history import cmd_history

        user = _make_user()
        msg = AsyncMock()
        msg.from_user = MagicMock(id=100, username="t", first_name="T")
        msg.answer = AsyncMock()

        mock_track = MagicMock()
        mock_track.title = "Song"
        mock_track.artist = "Artist"
        mock_entry = MagicMock()
        mock_entry.query = "test query"
        mock_entry.track_id = 1

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [(mock_entry, mock_track)]
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("bot.handlers.history.get_or_create_user", new_callable=AsyncMock, return_value=user), \
             patch("bot.handlers.history.async_session", return_value=mock_session):
            await cmd_history(msg)

        msg.answer.assert_called_once()
        call_args = msg.answer.call_args[0][0]
        assert "Artist" in call_args


@pytest.mark.asyncio
class TestCmdStats:
    async def test_shows_stats(self):
        from bot.handlers.history import cmd_stats

        user = _make_user()
        msg = AsyncMock()
        msg.from_user = MagicMock(id=100, username="t", first_name="T")
        msg.answer = AsyncMock()

        stats = {"total": 42, "week": 10, "top_artist": "Imagine Dragons"}

        with patch("bot.handlers.history.get_or_create_user", new_callable=AsyncMock, return_value=user), \
             patch("bot.handlers.history.get_user_stats", new_callable=AsyncMock, return_value=stats):
            await cmd_stats(msg)

        msg.answer.assert_called_once()

    async def test_stats_without_top_artist(self):
        from bot.handlers.history import cmd_stats

        user = _make_user()
        msg = AsyncMock()
        msg.from_user = MagicMock(id=100, username="t", first_name="T")
        msg.answer = AsyncMock()

        stats = {"total": 0, "week": 0, "top_artist": None}

        with patch("bot.handlers.history.get_or_create_user", new_callable=AsyncMock, return_value=user), \
             patch("bot.handlers.history.get_user_stats", new_callable=AsyncMock, return_value=stats):
            await cmd_stats(msg)

        msg.answer.assert_called_once()


@pytest.mark.asyncio
class TestTopPeriodCallback:
    async def test_invalid_period_ignored(self):
        from bot.handlers.history import handle_top_period

        cb = AsyncMock()
        cb.data = "top:invalid"
        cb.from_user = MagicMock(id=100)
        cb.answer = AsyncMock()

        await handle_top_period(cb)
        cb.answer.assert_called_once()

    async def test_valid_period_week(self):
        from bot.handlers.history import handle_top_period

        user = _make_user()
        cb = AsyncMock()
        cb.data = "top:week"
        cb.from_user = MagicMock(id=100, username="t", first_name="T")
        cb.answer = AsyncMock()
        cb.message = AsyncMock()
        cb.message.answer = AsyncMock()

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("bot.handlers.history.get_or_create_user", new_callable=AsyncMock, return_value=user), \
             patch("bot.handlers.history.async_session", return_value=mock_session):
            await handle_top_period(cb)

        cb.answer.assert_called_once()
