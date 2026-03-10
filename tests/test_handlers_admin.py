"""
Тесты для bot/handlers/admin.py — админ-панель.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_user(uid=100, username="admin", first_name="Admin", is_premium=True, lang="ru"):
    u = MagicMock()
    u.id = uid
    u.username = username
    u.first_name = first_name
    u.is_premium = is_premium
    u.language = lang
    return u


class TestIsAdminHandler:
    def test_admin_by_id(self):
        from bot.handlers.admin import _is_admin
        with patch("bot.handlers.admin.settings") as s:
            s.ADMIN_IDS = [111]
            assert _is_admin(111) is True
            assert _is_admin(222) is False


class TestAdminPanelKeyboard:
    def test_has_all_buttons(self):
        from bot.handlers.admin import _admin_panel_keyboard
        kb = _admin_panel_keyboard()
        all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "◎ Статистика" in all_texts
        assert "◈ Рассылка" in all_texts
        assert "◇ Дать Premium" in all_texts
        assert "✖ Бан" in all_texts


@pytest.mark.asyncio
class TestCmdAdmin:
    async def test_non_admin_ignored(self):
        from bot.handlers.admin import cmd_admin

        msg = AsyncMock()
        msg.from_user = MagicMock(id=999)
        msg.text = "/admin stats"
        msg.answer = AsyncMock()

        with patch("bot.handlers.admin._is_admin", return_value=False):
            await cmd_admin(msg, bot=AsyncMock())

        msg.answer.assert_not_called()

    async def test_admin_stats(self):
        from bot.handlers.admin import cmd_admin

        user = _make_user()
        msg = AsyncMock()
        msg.from_user = MagicMock(id=111, username="admin")
        msg.text = "/admin stats"
        msg.answer = AsyncMock()
        bot = AsyncMock()

        with patch("bot.handlers.admin._is_admin", return_value=True), \
             patch("bot.handlers.admin.get_or_create_user", new_callable=AsyncMock, return_value=user), \
             patch("bot.handlers.admin._build_detailed_stats", new_callable=AsyncMock, return_value="<b>Stats</b>"):
            await cmd_admin(msg, bot=bot)

        msg.answer.assert_called_once()


@pytest.mark.asyncio
class TestHandleAdminPanel:
    async def test_non_admin_rejected(self):
        from bot.handlers.admin import handle_admin_panel

        cb = AsyncMock()
        cb.from_user = MagicMock(id=999)
        cb.data = "action:admin"
        cb.answer = AsyncMock()

        with patch("bot.handlers.admin._is_admin", return_value=False):
            await handle_admin_panel(cb)

        cb.answer.assert_called_once()

    async def test_admin_shows_panel(self):
        from bot.handlers.admin import handle_admin_panel

        cb = AsyncMock()
        cb.from_user = MagicMock(id=111)
        cb.data = "action:admin"
        cb.answer = AsyncMock()
        cb.message = AsyncMock()
        cb.message.edit_text = AsyncMock()

        with patch("bot.handlers.admin._is_admin", return_value=True):
            await handle_admin_panel(cb)

        cb.answer.assert_called_once()
        cb.message.edit_text.assert_called_once()


@pytest.mark.asyncio
class TestAdmSkip:
    async def test_skip_sends_command(self, cache_with_fake_redis):
        from bot.handlers.admin import handle_adm_skip

        cb = AsyncMock()
        cb.from_user = MagicMock(id=111)
        cb.answer = AsyncMock()
        cb.message = AsyncMock()
        cb.message.edit_text = AsyncMock()

        with patch("bot.handlers.admin._is_admin", return_value=True), \
             patch("bot.handlers.admin.cache", cache_with_fake_redis):
            await handle_adm_skip(cb)

        cb.answer.assert_called_once()


class TestResolveUser:
    @pytest.mark.asyncio
    async def test_resolve_by_id(self):
        from bot.handlers.admin import _resolve_user

        mock_user = MagicMock()
        mock_user.id = 123

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=mock_user)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("bot.handlers.admin.async_session", return_value=mock_session):
            user, err = await _resolve_user("123")

        assert user is not None
        assert err is None

    @pytest.mark.asyncio
    async def test_resolve_by_username(self):
        from bot.handlers.admin import _resolve_user

        mock_user = MagicMock()
        mock_user.id = 456

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=None)  # not found by ID
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("bot.handlers.admin.async_session", return_value=mock_session):
            user, err = await _resolve_user("@testuser")

        assert user is not None
        assert user.id == 456

    @pytest.mark.asyncio
    async def test_not_found(self):
        from bot.handlers.admin import _resolve_user

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("bot.handlers.admin.async_session", return_value=mock_session):
            user, err = await _resolve_user("@unknown")

        assert user is None
        assert "не найден" in err


class TestAdminForwardState:
    def test_fwd_state_is_dict(self):
        from bot.handlers.admin import _admin_fwd_state
        assert isinstance(_admin_fwd_state, dict)


@pytest.mark.asyncio
class TestDetailedStatsCacheSection:
    async def test_build_detailed_stats_includes_cache_metrics(self):
        from bot.handlers.admin import _build_detailed_stats

        class _RowResult:
            def __init__(self, one_value=None, all_value=None):
                self._one_value = one_value
                self._all_value = all_value or []

            def one(self):
                return self._one_value

            def all(self):
                return self._all_value

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _RowResult((1, 0, 0, 0, 0, 0, 0, 0, 0, 0)),  # users
                _RowResult((0, 0, 0)),                       # payments
                _RowResult((0, 0)),                          # tracks
                _RowResult((0, 0, 0, 0, 0)),                 # listening
                _RowResult(all_value=[]),                    # source stats
                _RowResult(all_value=[]),                    # top queries
                _RowResult(all_value=[]),                    # top tracks
                _RowResult(all_value=[]),                    # lang stats
                _RowResult(all_value=[]),                    # top today
            ]
        )
        session.scalar = AsyncMock(side_effect=[0, 0, 0, 0, 0, 0])

        class _SessionCtx:
            async def __aenter__(self):
                return session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        fake_cache = MagicMock()
        fake_cache.get_runtime_metrics.return_value = {
            "gets": 10,
            "hits": 7,
            "hit_rate": 70.0,
            "avg_latency_ms": 2.5,
        }

        with patch("bot.handlers.admin.async_session", return_value=_SessionCtx()), \
             patch("bot.handlers.admin.cache", fake_cache):
            text = await _build_detailed_stats()

        assert "Cache performance" in text
        assert "70.0%" in text
        assert "2.50 ms" in text
