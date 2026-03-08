"""Tests for recommender/ai_dj.py — AI DJ recommendations and profile updates."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── get_recommendations ──────────────────────────────────────────────────

class TestGetRecommendations:
    @pytest.mark.asyncio
    @patch("recommender.ai_dj._build_recommendations", new_callable=AsyncMock)
    @patch("bot.services.cache.cache")
    async def test_returns_cached_results(self, mock_cache_obj, mock_build):
        from recommender.ai_dj import get_recommendations

        mock_cache_obj.redis.get = AsyncMock(return_value='[{"video_id": "abc", "title": "Test"}]')

        result = await get_recommendations(user_id=1, limit=10)
        assert len(result) == 1
        assert result[0]["video_id"] == "abc"
        mock_build.assert_not_called()

    @pytest.mark.asyncio
    @patch("recommender.ai_dj._build_recommendations", new_callable=AsyncMock)
    @patch("bot.services.cache.cache")
    async def test_builds_when_no_cache(self, mock_cache_obj, mock_build):
        from recommender.ai_dj import get_recommendations

        mock_cache_obj.redis.get = AsyncMock(return_value=None)
        mock_cache_obj.redis.setex = AsyncMock()
        mock_build.return_value = [{"video_id": "x", "title": "T"}]

        result = await get_recommendations(user_id=1, limit=10)
        assert len(result) == 1
        mock_build.assert_called_once_with(1, 10)

    @pytest.mark.asyncio
    @patch("recommender.ai_dj._build_recommendations", new_callable=AsyncMock)
    @patch("bot.services.cache.cache")
    async def test_returns_empty_on_no_data(self, mock_cache_obj, mock_build):
        from recommender.ai_dj import get_recommendations

        mock_cache_obj.redis.get = AsyncMock(return_value=None)
        mock_cache_obj.redis.setex = AsyncMock()
        mock_build.return_value = []

        result = await get_recommendations(user_id=1)
        assert result == []

    @pytest.mark.asyncio
    @patch("recommender.ai_dj._build_recommendations", new_callable=AsyncMock)
    @patch("bot.services.cache.cache")
    async def test_cache_error_falls_through(self, mock_cache_obj, mock_build):
        from recommender.ai_dj import get_recommendations

        mock_cache_obj.redis.get = AsyncMock(side_effect=Exception("redis down"))
        mock_cache_obj.redis.setex = AsyncMock(side_effect=Exception("redis down"))
        mock_build.return_value = [{"video_id": "y", "title": "T"}]

        result = await get_recommendations(user_id=1)
        assert len(result) == 1


# ── _track_to_dict ───────────────────────────────────────────────────────

class TestTrackToDict:
    def test_converts_track(self):
        from recommender.ai_dj import _track_to_dict
        track = MagicMock()
        track.source_id = "abc123"
        track.title = "Test Song"
        track.artist = "Artist"
        track.duration = 180
        track.source = "youtube"
        track.file_id = "fid_123"

        result = _track_to_dict(track)
        assert result["video_id"] == "abc123"
        assert result["title"] == "Test Song"
        assert result["uploader"] == "Artist"
        assert result["duration"] == 180
        assert result["duration_fmt"] == "3:00"
        assert result["source"] == "youtube"
        assert result["file_id"] == "fid_123"

    def test_handles_none_fields(self):
        from recommender.ai_dj import _track_to_dict
        track = MagicMock()
        track.source_id = "x"
        track.title = None
        track.artist = None
        track.duration = None
        track.source = None
        track.file_id = None

        result = _track_to_dict(track)
        assert result["title"] == "Unknown"
        assert result["uploader"] == "Unknown"
        assert result["duration_fmt"] == "?:??"


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
