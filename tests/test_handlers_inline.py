"""Tests for bot/handlers/inline.py — inline query handling."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_inline_query(query_text="", user_id=111):
    iq = AsyncMock()
    iq.query = query_text
    iq.answer = AsyncMock()
    from_user = MagicMock()
    from_user.id = user_id
    iq.from_user = from_user
    return iq


# ── handle_inline_query ──────────────────────────────────────────────────

class TestHandleInlineQuery:
    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self):
        from bot.handlers.inline import handle_inline_query
        iq = _make_inline_query("")
        await handle_inline_query(iq)
        iq.answer.assert_called_once_with([], cache_time=1)

    @pytest.mark.asyncio
    async def test_whitespace_query_returns_empty(self):
        from bot.handlers.inline import handle_inline_query
        iq = _make_inline_query("   ")
        await handle_inline_query(iq)
        iq.answer.assert_called_once_with([], cache_time=1)

    @pytest.mark.asyncio
    @patch("bot.handlers.inline.cache")
    @patch("bot.handlers.inline.search_tracks", new_callable=AsyncMock)
    async def test_query_with_cached_audio(self, mock_search, mock_cache):
        from bot.handlers.inline import handle_inline_query
        mock_search.return_value = [{
            "video_id": "abc",
            "title": "Test Song",
            "uploader": "Artist",
            "duration_fmt": "3:20",
        }]
        mock_cache.get_file_id = AsyncMock(return_value="AgACAgIAA...")

        iq = _make_inline_query("test")
        await handle_inline_query(iq)
        iq.answer.assert_called_once()
        results = iq.answer.call_args[0][0]
        assert len(results) == 1

    @pytest.mark.asyncio
    @patch("bot.handlers.inline.cache")
    @patch("bot.handlers.inline.search_tracks", new_callable=AsyncMock)
    async def test_query_without_cached_audio_returns_article(self, mock_search, mock_cache):
        from bot.handlers.inline import handle_inline_query
        mock_search.return_value = [{
            "video_id": "abc",
            "title": "Test Song",
            "uploader": "Artist",
            "duration_fmt": "3:20",
        }]
        mock_cache.get_file_id = AsyncMock(return_value=None)

        iq = _make_inline_query("test")
        await handle_inline_query(iq)
        iq.answer.assert_called_once()
        results = iq.answer.call_args[0][0]
        assert len(results) == 1

    @pytest.mark.asyncio
    @patch("bot.handlers.inline.cache")
    @patch("bot.handlers.inline.search_tracks", new_callable=AsyncMock)
    async def test_no_search_results(self, mock_search, mock_cache):
        from bot.handlers.inline import handle_inline_query
        mock_search.return_value = []

        iq = _make_inline_query("nonexistent")
        await handle_inline_query(iq)
        iq.answer.assert_called_once()
        results = iq.answer.call_args[0][0]
        assert len(results) == 0

    @pytest.mark.asyncio
    @patch("bot.handlers.inline.cache")
    @patch("bot.handlers.inline.search_tracks", new_callable=AsyncMock)
    async def test_multiple_results_mixed(self, mock_search, mock_cache):
        from bot.handlers.inline import handle_inline_query
        mock_search.return_value = [
            {"video_id": "a", "title": "Song A", "uploader": "Art1", "duration_fmt": "3:00"},
            {"video_id": "b", "title": "Song B", "uploader": "Art2", "duration_fmt": "4:00"},
        ]
        mock_cache.get_file_id = AsyncMock(side_effect=["AgACfid", None])

        iq = _make_inline_query("test")
        await handle_inline_query(iq)
        results = iq.answer.call_args[0][0]
        assert len(results) == 2
