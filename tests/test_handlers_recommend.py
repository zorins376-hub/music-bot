"""Tests for bot/handlers/recommend.py — onboarding, recommendations, AI DJ."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import make_callback, make_message


def _make_user(lang="ru", onboarded=False, fav_genres=None, fav_artists=None):
    u = MagicMock()
    u.id = 1
    u.language = lang
    u.onboarded = onboarded
    u.fav_genres = fav_genres
    u.fav_artists = fav_artists
    return u


# ── Keyboards ────────────────────────────────────────────────────────────

class TestKeyboards:
    def test_genre_keyboard_exists(self):
        from bot.handlers.recommend import _GENRE_KEYBOARD
        assert len(_GENRE_KEYBOARD.inline_keyboard) == 3
        total_btns = sum(len(row) for row in _GENRE_KEYBOARD.inline_keyboard)
        assert total_btns == 8  # 3+3+2

    def test_vibe_keyboard_exists(self):
        from bot.handlers.recommend import _VIBE_KEYBOARD
        assert len(_VIBE_KEYBOARD.inline_keyboard) == 2
        total_btns = sum(len(row) for row in _VIBE_KEYBOARD.inline_keyboard)
        assert total_btns == 4

    def test_genre_callback_data_format(self):
        from bot.handlers.recommend import _GENRE_KEYBOARD
        for row in _GENRE_KEYBOARD.inline_keyboard:
            for btn in row:
                assert btn.callback_data.startswith("ob_genre:")

    def test_vibe_callback_data_format(self):
        from bot.handlers.recommend import _VIBE_KEYBOARD
        for row in _VIBE_KEYBOARD.inline_keyboard:
            for btn in row:
                assert btn.callback_data.startswith("ob_vibe:")


# ── OnboardState ─────────────────────────────────────────────────────────

class TestOnboardState:
    def test_states_exist(self):
        from bot.handlers.recommend import OnboardState
        assert OnboardState.waiting_artists is not None


# ── handle_recommend ─────────────────────────────────────────────────────

class TestHandleRecommend:
    @pytest.mark.asyncio
    @patch("bot.handlers.recommend.async_session")
    @patch("bot.handlers.recommend.get_or_create_user", new_callable=AsyncMock)
    async def test_new_user_starts_onboarding(self, mock_goc, mock_sess):
        from bot.handlers.recommend import handle_recommend
        user = _make_user(onboarded=False)
        mock_goc.return_value = user

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar.return_value = 0  # no plays
        session.execute = AsyncMock(return_value=result_mock)
        mock_sess.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

        cb = make_callback("action:recommend")
        state = AsyncMock()
        await handle_recommend(cb, state)
        cb.answer.assert_called()
        cb.message.answer.assert_called()  # genre keyboard sent

    @pytest.mark.asyncio
    @patch("bot.handlers.recommend._show_recommendations", new_callable=AsyncMock)
    @patch("bot.handlers.recommend.get_or_create_user", new_callable=AsyncMock)
    async def test_onboarded_user_gets_recommendations(self, mock_goc, mock_show):
        from bot.handlers.recommend import handle_recommend
        user = _make_user(onboarded=True)
        mock_goc.return_value = user

        cb = make_callback("action:recommend")
        state = AsyncMock()
        await handle_recommend(cb, state)
        mock_show.assert_called_once()


# ── handle_genre_select ──────────────────────────────────────────────────

class TestHandleGenreSelect:
    @pytest.mark.asyncio
    @patch("bot.handlers.recommend.async_session")
    @patch("bot.handlers.recommend.get_or_create_user", new_callable=AsyncMock)
    async def test_genre_select_saves_and_shows_vibe(self, mock_goc, mock_sess):
        from bot.handlers.recommend import handle_genre_select
        user = _make_user()
        mock_goc.return_value = user

        current_user = MagicMock()
        current_user.fav_genres = []
        session = AsyncMock()
        session.get = AsyncMock(return_value=current_user)
        session.execute = AsyncMock()
        mock_sess.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

        cb = make_callback("ob_genre:rock")
        cb.data = "ob_genre:rock"
        state = AsyncMock()
        await handle_genre_select(cb, state)
        cb.message.edit_text.assert_called()
        session.execute.assert_called()


# ── handle_vibe_select ───────────────────────────────────────────────────

class TestHandleVibeSelect:
    @pytest.mark.asyncio
    @patch("bot.handlers.recommend.async_session")
    @patch("bot.handlers.recommend.get_or_create_user", new_callable=AsyncMock)
    async def test_vibe_select_saves_and_asks_artists(self, mock_goc, mock_sess):
        from bot.handlers.recommend import handle_vibe_select
        mock_goc.return_value = _make_user()

        session = AsyncMock()
        mock_sess.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

        cb = make_callback("ob_vibe:deep")
        cb.data = "ob_vibe:deep"
        state = AsyncMock()
        await handle_vibe_select(cb, state)
        state.set_state.assert_called_once()
        cb.message.edit_text.assert_called()


# ── handle_artists_input ─────────────────────────────────────────────────

class TestHandleArtistsInput:
    @pytest.mark.asyncio
    @patch("bot.handlers.recommend.async_session")
    @patch("bot.handlers.recommend.get_or_create_user", new_callable=AsyncMock)
    async def test_artists_parsed_and_saved(self, mock_goc, mock_sess):
        from bot.handlers.recommend import handle_artists_input
        mock_goc.return_value = _make_user()

        session = AsyncMock()
        mock_sess.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

        msg = make_message("Rammstein, Korn, Slipknot")
        msg.text = "Rammstein, Korn, Slipknot"
        state = AsyncMock()
        await handle_artists_input(msg, state)
        state.clear.assert_called_once()
        msg.answer.assert_called()

    @pytest.mark.asyncio
    @patch("bot.handlers.recommend.async_session")
    @patch("bot.handlers.recommend.get_or_create_user", new_callable=AsyncMock)
    async def test_artists_max_5(self, mock_goc, mock_sess):
        from bot.handlers.recommend import handle_artists_input
        mock_goc.return_value = _make_user()

        session = AsyncMock()
        mock_sess.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

        msg = make_message("A, B, C, D, E, F, G")
        msg.text = "A, B, C, D, E, F, G"
        state = AsyncMock()
        await handle_artists_input(msg, state)
        # Should still complete successfully
        state.clear.assert_called_once()


# ── _fmt_dur ─────────────────────────────────────────────────────────────

class TestFmtDur:
    def test_normal(self):
        from bot.handlers.recommend import _fmt_dur
        assert _fmt_dur(200) == "3:20"

    def test_none(self):
        from bot.handlers.recommend import _fmt_dur
        assert _fmt_dur(None) == "?:??"

    def test_zero(self):
        from bot.handlers.recommend import _fmt_dur
        assert _fmt_dur(0) == "?:??"

    def test_exact_minute(self):
        from bot.handlers.recommend import _fmt_dur
        assert _fmt_dur(60) == "1:00"
