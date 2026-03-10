"""Tests for bot/handlers/search.py — search cascade, URL resolution, download flow."""
import secrets
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import make_callback, make_message, make_tg_user


# ── Helper functions ─────────────────────────────────────────────────────

def _make_user(lang="ru", is_banned=False, is_premium=False, quality="192"):
    u = MagicMock()
    u.id = 1
    u.language = lang
    u.is_banned = is_banned
    u.is_premium = is_premium
    u.quality = quality
    return u


def _track_info(video_id="abc123", title="Test Song", uploader="Artist"):
    return {
        "video_id": video_id,
        "title": title,
        "uploader": uploader,
        "duration": 200,
        "duration_fmt": "3:20",
        "source": "youtube",
    }


# ── _track_caption ───────────────────────────────────────────────────────

class TestTrackCaption:
    def test_caption_with_year(self):
        from bot.handlers.search import _track_caption
        info = {"duration_fmt": "3:42", "upload_year": 2019}
        result = _track_caption("ru", info, 192)
        assert "3:42" in result
        assert "192" in result

    def test_caption_without_year(self):
        from bot.handlers.search import _track_caption
        info = {"duration_fmt": "2:10", "upload_year": None}
        result = _track_caption("ru", info, 128)
        assert "2:10" in result
        assert "128" in result

    def test_caption_missing_duration(self):
        from bot.handlers.search import _track_caption
        info = {}
        result = _track_caption("ru", info, 320)
        assert "?:??" in result


# ── _build_results_keyboard ──────────────────────────────────────────────

class TestBuildResultsKeyboard:
    def test_keyboard_has_correct_amount_of_buttons(self):
        from bot.handlers.search import _build_results_keyboard
        results = [_track_info(f"id{i}", f"Song {i}") for i in range(3)]
        kb = _build_results_keyboard(results, "session123")
        assert len(kb.inline_keyboard) == 3

    def test_keyboard_single_result(self):
        from bot.handlers.search import _build_results_keyboard
        kb = _build_results_keyboard([_track_info()], "s1")
        assert len(kb.inline_keyboard) == 1
        assert "Artist" in kb.inline_keyboard[0][0].text

    def test_keyboard_empty_results(self):
        from bot.handlers.search import _build_results_keyboard
        kb = _build_results_keyboard([], "s1")
        assert len(kb.inline_keyboard) == 0


# ── _fmt_duration ────────────────────────────────────────────────────────

class TestFmtDuration:
    def test_normal(self):
        from bot.handlers.search import _fmt_duration
        assert _fmt_duration(200) == "3:20"

    def test_zero(self):
        from bot.handlers.search import _fmt_duration
        assert _fmt_duration(0) == "0:00"

    def test_none(self):
        from bot.handlers.search import _fmt_duration
        assert _fmt_duration(None) == "?:??"

    def test_exact_minute(self):
        from bot.handlers.search import _fmt_duration
        assert _fmt_duration(60) == "1:00"

    def test_under_minute(self):
        from bot.handlers.search import _fmt_duration
        assert _fmt_duration(45) == "0:45"


# ── _feedback_keyboard ──────────────────────────────────────────────────

class TestFeedbackKeyboard:
    def test_keyboard_structure(self):
        from bot.handlers.search import _feedback_keyboard
        kb = _feedback_keyboard(42)
        row = kb.inline_keyboard[0]
        assert len(row) == 4  # like, dislike, add to playlist, add to queue
        assert len(kb.inline_keyboard) == 3  # row2 = lyrics/fav/share, row3 = similar


# ── cmd_search ───────────────────────────────────────────────────────────

class TestCmdSearch:
    @pytest.mark.asyncio
    @patch("bot.handlers.search.get_or_create_user", new_callable=AsyncMock)
    async def test_search_no_query_shows_prompt(self, mock_goc):
        from bot.handlers.search import cmd_search
        mock_goc.return_value = _make_user()
        msg = make_message("/search")
        msg.text = "/search"
        await cmd_search(msg)
        msg.answer.assert_called_once()

    @pytest.mark.asyncio
    @patch("bot.handlers.search._do_search", new_callable=AsyncMock)
    async def test_search_with_query_calls_do_search(self, mock_do):
        from bot.handlers.search import cmd_search
        msg = make_message("/search test query")
        msg.text = "/search test query"
        await cmd_search(msg)
        mock_do.assert_called_once_with(msg, "test query")


# ── _do_search banned user ───────────────────────────────────────────────

class TestDoSearchBanned:
    @pytest.mark.asyncio
    @patch("bot.handlers.search.get_or_create_user", new_callable=AsyncMock)
    async def test_banned_user_ignored(self, mock_goc):
        from bot.handlers.search import _do_search
        mock_goc.return_value = _make_user(is_banned=True)
        msg = make_message("test query")
        await _do_search(msg, "test query")
        # banned user returns silently after answer (status msg)
        msg.answer_audio.assert_not_called()


# ── _do_search rate limit ────────────────────────────────────────────────

class TestDoSearchRateLimit:
    @pytest.mark.asyncio
    @patch("bot.handlers.search.search_local_tracks", new_callable=AsyncMock, return_value=[])
    @patch("bot.handlers.search.cache")
    @patch("bot.handlers.search.get_or_create_user", new_callable=AsyncMock)
    async def test_rate_limited_user(self, mock_goc, mock_cache, mock_local):
        from bot.handlers.search import _do_search
        user = _make_user()
        mock_goc.return_value = user
        mock_cache.check_rate_limit = AsyncMock(return_value=(False, 10))
        mock_cache.redis = AsyncMock()
        mock_cache.redis.get = AsyncMock(return_value=None)

        msg = make_message("test")
        msg.from_user.id = 999  # not admin
        await _do_search(msg, "test")
        assert msg.answer.call_count >= 1  # at least rate limit message


# ── _do_search Spotify URL detection ─────────────────────────────────────

class TestDoSearchSpotify:
    @pytest.mark.asyncio
    @patch("bot.handlers.search.requests_total")
    @patch("bot.handlers.search.record_listening_event", new_callable=AsyncMock)
    @patch("bot.handlers.search.resolve_spotify_url", new_callable=AsyncMock)
    @patch("bot.handlers.search.is_spotify_url", return_value=True)
    @patch("bot.handlers.search.cache")
    @patch("bot.handlers.search.get_or_create_user", new_callable=AsyncMock)
    async def test_spotify_url_resolve(self, mock_goc, mock_cache, mock_is_sp,
                                        mock_resolve, mock_record, mock_metrics):
        from bot.handlers.search import _do_search
        mock_goc.return_value = _make_user()
        mock_cache.check_rate_limit = AsyncMock(return_value=(True, 0))
        mock_cache.redis = AsyncMock()
        mock_cache.redis.get = AsyncMock(return_value=None)
        mock_cache.store_search = AsyncMock()
        mock_resolve.return_value = _track_info()
        mock_metrics.labels = MagicMock(return_value=MagicMock())

        msg = make_message("https://open.spotify.com/track/abc")
        msg.from_user.id = 999
        status_msg = AsyncMock()
        msg.answer = AsyncMock(return_value=status_msg)
        await _do_search(msg, "https://open.spotify.com/track/abc")
        mock_resolve.assert_called_once()

    @pytest.mark.asyncio
    @patch("bot.handlers.search.resolve_spotify_url", new_callable=AsyncMock, return_value=None)
    @patch("bot.handlers.search.is_spotify_url", return_value=True)
    @patch("bot.handlers.search.cache")
    @patch("bot.handlers.search.get_or_create_user", new_callable=AsyncMock)
    async def test_spotify_url_no_results(self, mock_goc, mock_cache, mock_is_sp, mock_resolve):
        from bot.handlers.search import _do_search
        mock_goc.return_value = _make_user()
        mock_cache.check_rate_limit = AsyncMock(return_value=(True, 0))
        mock_cache.redis = AsyncMock()
        mock_cache.redis.get = AsyncMock(return_value=None)

        msg = make_message("https://open.spotify.com/track/abc")
        msg.from_user.id = 999
        status_msg = AsyncMock()
        msg.answer = AsyncMock(return_value=status_msg)
        await _do_search(msg, "https://open.spotify.com/track/abc")
        status_msg.edit_text.assert_called()


# ── _do_search search cascade ───────────────────────────────────────────

class TestSearchCascade:
    @pytest.mark.asyncio
    @patch("bot.handlers.search.requests_total")
    @patch("bot.handlers.search.record_listening_event", new_callable=AsyncMock)
    @patch("bot.handlers.search.cache")
    @patch("bot.handlers.search.search_local_tracks", new_callable=AsyncMock)
    @patch("bot.handlers.search.is_spotify_url", return_value=False)
    @patch("bot.handlers.search.is_yandex_music_url", return_value=False)
    @patch("bot.handlers.search.search_yandex", new_callable=AsyncMock)
    @patch("bot.handlers.search.get_or_create_user", new_callable=AsyncMock)
    async def test_yandex_results_used(self, mock_goc, mock_ym, mock_is_ym, mock_is_sp,
                                        mock_local, mock_cache, mock_record, mock_metrics):
        from bot.handlers.search import _do_search
        mock_goc.return_value = _make_user()
        mock_cache.check_rate_limit = AsyncMock(return_value=(True, 0))
        mock_cache.redis = AsyncMock()
        mock_cache.redis.get = AsyncMock(return_value="10")  # max_results
        mock_cache.store_search = AsyncMock()
        mock_cache.get_query_cache = AsyncMock(return_value=None)
        mock_cache.set_query_cache = AsyncMock()
        mock_local.return_value = []
        mock_ym.return_value = [_track_info()]
        mock_metrics.labels = MagicMock(return_value=MagicMock())

        msg = make_message("test query")
        msg.from_user.id = 999
        status_msg = AsyncMock()
        msg.answer = AsyncMock(return_value=status_msg)
        msg.bot = AsyncMock()
        await _do_search(msg, "test query")
        mock_ym.assert_called_once()
        mock_cache.store_search.assert_called_once()

    @pytest.mark.asyncio
    @patch("bot.handlers.search.requests_total")
    @patch("bot.handlers.search.record_listening_event", new_callable=AsyncMock)
    @patch("bot.handlers.search.cache")
    @patch("bot.handlers.search.search_local_tracks", new_callable=AsyncMock, return_value=[])
    @patch("bot.handlers.search.is_spotify_url", return_value=False)
    @patch("bot.handlers.search.is_yandex_music_url", return_value=False)
    @patch("bot.handlers.search.search_yandex", new_callable=AsyncMock, return_value=[])
    @patch("bot.handlers.search.search_spotify", new_callable=AsyncMock, return_value=[])
    @patch("bot.handlers.search.search_vk", new_callable=AsyncMock, return_value=[])
    @patch("bot.handlers.search.search_tracks", new_callable=AsyncMock, return_value=[])
    @patch("bot.handlers.search.get_or_create_user", new_callable=AsyncMock)
    async def test_no_results_at_all(self, mock_goc, mock_yt, mock_vk, mock_sp, mock_ym,
                                      mock_is_ym, mock_is_sp, mock_local, mock_cache,
                                      mock_record, mock_metrics):
        from bot.handlers.search import _do_search
        mock_goc.return_value = _make_user()
        mock_cache.check_rate_limit = AsyncMock(return_value=(True, 0))
        mock_cache.redis = AsyncMock()
        mock_cache.redis.get = AsyncMock(return_value="10")
        mock_cache.get_query_cache = AsyncMock(return_value=None)
        mock_cache.set_query_cache = AsyncMock()
        mock_metrics.labels = MagicMock(return_value=MagicMock())

        msg = make_message("nonexistent track")
        msg.from_user.id = 999
        status_msg = AsyncMock()
        msg.answer = AsyncMock(return_value=status_msg)
        msg.bot = AsyncMock()
        await _do_search(msg, "nonexistent track")
        status_msg.edit_text.assert_called()  # "no_results"


# ── handle_text (private vs group) ───────────────────────────────────────

class TestHandleText:
    @pytest.mark.asyncio
    @patch("bot.handlers.search._do_search", new_callable=AsyncMock)
    async def test_private_message_triggers_search(self, mock_do):
        from bot.handlers.search import handle_text
        msg = make_message("some song name", chat_type="private")
        msg.text = "some song name"
        await handle_text(msg)
        mock_do.assert_called_once()

    @pytest.mark.asyncio
    @patch("bot.handlers.search._do_search", new_callable=AsyncMock)
    async def test_group_message_without_trigger_ignored(self, mock_do):
        from bot.handlers.search import handle_text
        msg = make_message("some song name", chat_type="group")
        msg.text = "some song name"
        await handle_text(msg)
        mock_do.assert_not_called()

    @pytest.mark.asyncio
    @patch("bot.handlers.search._do_search", new_callable=AsyncMock)
    async def test_group_message_with_trigger_prefix(self, mock_do):
        from bot.handlers.search import handle_text
        msg = make_message("включи Rammstein", chat_type="group")
        msg.text = "включи Rammstein"
        await handle_text(msg)
        mock_do.assert_called_once_with(msg, "Rammstein")

    @pytest.mark.asyncio
    @patch("bot.handlers.search._do_search", new_callable=AsyncMock)
    async def test_text_with_play_prefix(self, mock_do):
        from bot.handlers.search import handle_text
        msg = make_message("play Metallica", chat_type="private")
        msg.text = "play Metallica"
        await handle_text(msg)
        mock_do.assert_called_once_with(msg, "Metallica")

    @pytest.mark.asyncio
    @patch("bot.handlers.search._do_search", new_callable=AsyncMock)
    async def test_empty_text_after_strip(self, mock_do):
        from bot.handlers.search import handle_text
        msg = make_message("   ", chat_type="private")
        msg.text = "   "
        await handle_text(msg)
        mock_do.assert_not_called()


# ── handle_track_select ──────────────────────────────────────────────────

class TestHandleTrackSelect:
    @pytest.mark.asyncio
    @patch("bot.handlers.search.cache")
    @patch("bot.handlers.search.get_or_create_user", new_callable=AsyncMock)
    async def test_session_expired(self, mock_goc, mock_cache):
        from bot.handlers.search import handle_track_select, TrackCallback
        mock_goc.return_value = _make_user()
        mock_cache.get_search = AsyncMock(return_value=None)

        cb = make_callback()
        cb_data = TrackCallback(sid="expired", i=0)
        await handle_track_select(cb, cb_data)
        cb.message.answer.assert_called()

    @pytest.mark.asyncio
    @patch("bot.handlers.search.cache")
    @patch("bot.handlers.search.get_or_create_user", new_callable=AsyncMock)
    async def test_banned_user_ignored(self, mock_goc, mock_cache):
        from bot.handlers.search import handle_track_select, TrackCallback
        mock_goc.return_value = _make_user(is_banned=True)
        mock_cache.get_search = AsyncMock(return_value=[_track_info()])

        cb = make_callback()
        cb_data = TrackCallback(sid="s1", i=0)
        await handle_track_select(cb, cb_data)
        cb.message.answer_audio.assert_not_called()

    @pytest.mark.asyncio
    @patch("bot.handlers.search._post_download", new_callable=AsyncMock, return_value=42)
    @patch("bot.handlers.search.cache")
    @patch("bot.handlers.search.get_or_create_user", new_callable=AsyncMock)
    async def test_cached_file_id_sends_audio(self, mock_goc, mock_cache, mock_post):
        from bot.handlers.search import handle_track_select, TrackCallback
        mock_goc.return_value = _make_user()
        mock_cache.get_search = AsyncMock(return_value=[_track_info()])
        mock_cache.get_file_id = AsyncMock(return_value="AgACAgIAAx0...")
        mock_cache.redis = AsyncMock()
        mock_cache.redis.get = AsyncMock(return_value=None)

        cb = make_callback()
        cb_data = TrackCallback(sid="s1", i=0)
        await handle_track_select(cb, cb_data)
        cb.message.answer_audio.assert_called_once()


# ── handle_feedback ──────────────────────────────────────────────────────

class TestHandleFeedback:
    @pytest.mark.asyncio
    @patch("bot.handlers.search.record_listening_event", new_callable=AsyncMock)
    @patch("bot.handlers.search.get_or_create_user", new_callable=AsyncMock)
    async def test_like_feedback(self, mock_goc, mock_record):
        from bot.handlers.search import handle_feedback, FeedbackCallback
        mock_goc.return_value = _make_user()
        cb = make_callback()
        cb_data = FeedbackCallback(tid=42, act="like")
        await handle_feedback(cb, cb_data)
        mock_record.assert_called_once()
        cb.answer.assert_called()

    @pytest.mark.asyncio
    @patch("bot.handlers.search.record_listening_event", new_callable=AsyncMock)
    @patch("bot.handlers.search.get_or_create_user", new_callable=AsyncMock)
    async def test_dislike_feedback(self, mock_goc, mock_record):
        from bot.handlers.search import handle_feedback, FeedbackCallback
        mock_goc.return_value = _make_user()
        cb = make_callback()
        cb_data = FeedbackCallback(tid=42, act="dislike")
        await handle_feedback(cb, cb_data)
        mock_record.assert_called_once()


# ── _post_download ───────────────────────────────────────────────────────

class TestPostDownload:
    @pytest.mark.asyncio
    @patch("bot.handlers.search.record_listening_event", new_callable=AsyncMock)
    @patch("bot.handlers.search.upsert_track", new_callable=AsyncMock)
    @patch("bot.handlers.search.increment_request_count", new_callable=AsyncMock)
    async def test_post_download_returns_track_id(self, mock_inc, mock_upsert, mock_record):
        from bot.handlers.search import _post_download
        mock_track = MagicMock()
        mock_track.id = 42
        mock_upsert.return_value = mock_track

        with patch("bot.handlers.search.async_session", create=True):
            result = await _post_download(1, _track_info(), "file123", 192)
        mock_inc.assert_called_once_with(1)

    @pytest.mark.asyncio
    @patch("bot.handlers.search.record_listening_event", new_callable=AsyncMock)
    @patch("bot.handlers.search.upsert_track", new_callable=AsyncMock, side_effect=Exception("DB error"))
    @patch("bot.handlers.search.increment_request_count", new_callable=AsyncMock)
    async def test_post_download_handles_db_error(self, mock_inc, mock_upsert, mock_record):
        from bot.handlers.search import _post_download
        result = await _post_download(1, _track_info(), "file123", 192)
        assert result == 0


# ── _get_bot_setting ─────────────────────────────────────────────────────

class TestGetBotSetting:
    @pytest.mark.asyncio
    @patch("bot.handlers.search.cache")
    async def test_returns_redis_value(self, mock_cache):
        from bot.handlers.search import _get_bot_setting
        mock_cache.redis = AsyncMock()
        mock_cache.redis.get = AsyncMock(return_value="5")
        result = await _get_bot_setting("max_results", "10")
        assert result == "5"

    @pytest.mark.asyncio
    @patch("bot.handlers.search.cache")
    async def test_returns_default_when_not_set(self, mock_cache):
        from bot.handlers.search import _get_bot_setting
        mock_cache.redis = AsyncMock()
        mock_cache.redis.get = AsyncMock(return_value=None)
        result = await _get_bot_setting("max_results", "10")
        assert result == "10"
