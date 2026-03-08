"""Tests for recommender/ai_dj.py — AI DJ recommendations and profile updates."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── get_recommendations ──────────────────────────────────────────────────

class TestGetRecommendations:
    @pytest.mark.asyncio
    async def test_returns_empty_list(self):
        from recommender.ai_dj import get_recommendations
        result = await get_recommendations(user_id=1, limit=10)
        assert result == []

    @pytest.mark.asyncio
    async def test_default_limit(self):
        from recommender.ai_dj import get_recommendations
        result = await get_recommendations(user_id=1)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_custom_limit(self):
        from recommender.ai_dj import get_recommendations
        result = await get_recommendations(user_id=1, limit=5)
        assert isinstance(result, list)


# ── update_user_profile ──────────────────────────────────────────────────

class TestUpdateUserProfile:
    @pytest.mark.asyncio
    @patch("bot.models.base.async_session")
    async def test_updates_with_data(self, mock_sess):
        from recommender.ai_dj import update_user_profile

        session = AsyncMock()
        # avg BPM result
        bpm_result = MagicMock()
        bpm_result.scalar.return_value = 120.5
        # genre result
        genre_result = MagicMock()
        genre_result.all.return_value = [("rock",), ("pop",)]
        # update result (3rd call to execute)
        update_result = MagicMock()
        session.execute = AsyncMock(side_effect=[bpm_result, genre_result, update_result])
        mock_sess.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

        await update_user_profile(user_id=1)
        session.commit.assert_called_once()

    @pytest.mark.asyncio
    @patch("bot.models.base.async_session")
    async def test_no_data_skips_update(self, mock_sess):
        from recommender.ai_dj import update_user_profile

        session = AsyncMock()
        bpm_result = MagicMock()
        bpm_result.scalar.return_value = None
        genre_result = MagicMock()
        genre_result.all.return_value = []
        session.execute = AsyncMock(side_effect=[bpm_result, genre_result])
        mock_sess.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

        await update_user_profile(user_id=1)
        # No commit since no data to update
        session.commit.assert_not_called()

    @pytest.mark.asyncio
    @patch("bot.models.base.async_session")
    async def test_only_genres_no_bpm(self, mock_sess):
        from recommender.ai_dj import update_user_profile

        session = AsyncMock()
        bpm_result = MagicMock()
        bpm_result.scalar.return_value = None
        genre_result = MagicMock()
        genre_result.all.return_value = [("electronic",)]
        update_result = MagicMock()
        session.execute = AsyncMock(side_effect=[bpm_result, genre_result, update_result])
        mock_sess.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

        await update_user_profile(user_id=1)
        session.commit.assert_called_once()
