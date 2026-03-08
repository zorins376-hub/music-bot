"""Tests for bot/handlers/queue.py — listening queue."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import make_callback, make_message


def _make_user(uid=1, lang="ru"):
    u = MagicMock()
    u.id = uid
    u.language = lang
    return u


_SAMPLE_TRACK = {
    "video_id": "abc123",
    "title": "Test Song",
    "uploader": "Artist",
    "duration": 200,
    "duration_fmt": "3:20",
    "source": "youtube",
    "file_id": "fid_abc",
}


# ── Queue helpers ────────────────────────────────────────────────────────

class TestQueueHelpers:
    @pytest.mark.asyncio
    @patch("bot.handlers.queue.cache")
    async def test_get_queue_empty(self, mock_cache):
        from bot.handlers.queue import _get_queue
        mock_cache.redis.get = AsyncMock(return_value=None)
        result = await _get_queue(1)
        assert result == []

    @pytest.mark.asyncio
    @patch("bot.handlers.queue.cache")
    async def test_get_queue_with_data(self, mock_cache):
        from bot.handlers.queue import _get_queue
        mock_cache.redis.get = AsyncMock(
            return_value=json.dumps([_SAMPLE_TRACK])
        )
        result = await _get_queue(1)
        assert len(result) == 1
        assert result[0]["title"] == "Test Song"

    @pytest.mark.asyncio
    @patch("bot.handlers.queue.cache")
    async def test_set_queue(self, mock_cache):
        from bot.handlers.queue import _set_queue
        mock_cache.redis.setex = AsyncMock()
        await _set_queue(1, [_SAMPLE_TRACK])
        mock_cache.redis.setex.assert_called_once()

    @pytest.mark.asyncio
    @patch("bot.handlers.queue.cache")
    async def test_get_queue_redis_error(self, mock_cache):
        from bot.handlers.queue import _get_queue
        mock_cache.redis.get = AsyncMock(side_effect=Exception("fail"))
        result = await _get_queue(1)
        assert result == []


# ── add_to_queue ─────────────────────────────────────────────────────────

class TestAddToQueue:
    @pytest.mark.asyncio
    @patch("bot.handlers.queue._set_queue", new_callable=AsyncMock)
    @patch("bot.handlers.queue._get_queue", new_callable=AsyncMock)
    async def test_add_track(self, mock_get, mock_set):
        from bot.handlers.queue import add_to_queue
        mock_get.return_value = []
        msg = await add_to_queue(1, _SAMPLE_TRACK, "ru")
        assert "Test Song" in msg
        mock_set.assert_called_once()

    @pytest.mark.asyncio
    @patch("bot.handlers.queue._set_queue", new_callable=AsyncMock)
    @patch("bot.handlers.queue._get_queue", new_callable=AsyncMock)
    async def test_queue_full(self, mock_get, mock_set):
        from bot.handlers.queue import add_to_queue
        mock_get.return_value = [_SAMPLE_TRACK] * 50
        msg = await add_to_queue(1, _SAMPLE_TRACK, "ru")
        assert "50" in msg
        mock_set.assert_not_called()


# ── /queue command ───────────────────────────────────────────────────────

class TestCmdQueue:
    @pytest.mark.asyncio
    @patch("bot.handlers.queue._get_queue", new_callable=AsyncMock)
    @patch("bot.handlers.queue.get_or_create_user", new_callable=AsyncMock)
    async def test_empty_queue(self, mock_goc, mock_get):
        from bot.handlers.queue import cmd_queue
        mock_goc.return_value = _make_user()
        mock_get.return_value = []

        msg = make_message("/queue")
        await cmd_queue(msg)
        msg.answer.assert_called()

    @pytest.mark.asyncio
    @patch("bot.handlers.queue._get_queue", new_callable=AsyncMock)
    @patch("bot.handlers.queue.get_or_create_user", new_callable=AsyncMock)
    async def test_queue_with_items(self, mock_goc, mock_get):
        from bot.handlers.queue import cmd_queue
        mock_goc.return_value = _make_user()
        mock_get.return_value = [_SAMPLE_TRACK, _SAMPLE_TRACK]

        msg = make_message("/queue")
        await cmd_queue(msg)
        msg.answer.assert_called()
        call_text = msg.answer.call_args[0][0]
        assert "2" in call_text


# ── /next command ────────────────────────────────────────────────────────

class TestCmdNext:
    @pytest.mark.asyncio
    @patch("bot.handlers.queue._set_queue", new_callable=AsyncMock)
    @patch("bot.handlers.queue._get_queue", new_callable=AsyncMock)
    @patch("bot.handlers.queue.get_or_create_user", new_callable=AsyncMock)
    async def test_next_empty(self, mock_goc, mock_get, mock_set):
        from bot.handlers.queue import cmd_next
        mock_goc.return_value = _make_user()
        mock_get.return_value = []

        msg = make_message("/next")
        await cmd_next(msg)
        msg.answer.assert_called()

    @pytest.mark.asyncio
    @patch("bot.handlers.queue._set_queue", new_callable=AsyncMock)
    @patch("bot.handlers.queue._get_queue", new_callable=AsyncMock)
    @patch("bot.handlers.queue.get_or_create_user", new_callable=AsyncMock)
    async def test_next_with_file_id(self, mock_goc, mock_get, mock_set):
        from bot.handlers.queue import cmd_next
        mock_goc.return_value = _make_user()
        mock_get.return_value = [_SAMPLE_TRACK]

        msg = make_message("/next")
        await cmd_next(msg)
        msg.answer_audio.assert_called_once()
        mock_set.assert_called_once_with(1, [])  # queue now empty


# ── Queue callbacks ──────────────────────────────────────────────────────

class TestQueueCallbacks:
    @pytest.mark.asyncio
    @patch("bot.handlers.queue._show_queue", new_callable=AsyncMock)
    @patch("bot.handlers.queue._set_queue", new_callable=AsyncMock)
    @patch("bot.handlers.queue._get_queue", new_callable=AsyncMock)
    @patch("bot.handlers.queue.get_or_create_user", new_callable=AsyncMock)
    async def test_shuffle(self, mock_goc, mock_get, mock_set, mock_show):
        from bot.handlers.queue import handle_queue_cb
        from bot.callbacks import QueueCb
        mock_goc.return_value = _make_user()
        mock_get.return_value = [_SAMPLE_TRACK] * 3

        cb = make_callback(QueueCb(act="shuf").pack())
        cb_data = QueueCb(act="shuf")
        await handle_queue_cb(cb, cb_data)
        mock_set.assert_called_once()
        cb.answer.assert_called()

    @pytest.mark.asyncio
    @patch("bot.handlers.queue._show_queue", new_callable=AsyncMock)
    @patch("bot.handlers.queue._set_queue", new_callable=AsyncMock)
    @patch("bot.handlers.queue.get_or_create_user", new_callable=AsyncMock)
    async def test_clear(self, mock_goc, mock_set, mock_show):
        from bot.handlers.queue import handle_queue_cb
        from bot.callbacks import QueueCb
        mock_goc.return_value = _make_user()

        cb = make_callback(QueueCb(act="clr").pack())
        cb_data = QueueCb(act="clr")
        await handle_queue_cb(cb, cb_data)
        mock_set.assert_called_once_with(1, [])
        cb.answer.assert_called()

    @pytest.mark.asyncio
    @patch("bot.handlers.queue._show_queue", new_callable=AsyncMock)
    @patch("bot.handlers.queue._get_queue", new_callable=AsyncMock)
    @patch("bot.handlers.queue.get_or_create_user", new_callable=AsyncMock)
    async def test_next_empty_alert(self, mock_goc, mock_get, mock_show):
        from bot.handlers.queue import handle_queue_cb
        from bot.callbacks import QueueCb
        mock_goc.return_value = _make_user()
        mock_get.return_value = []

        cb = make_callback(QueueCb(act="next").pack())
        cb_data = QueueCb(act="next")
        await handle_queue_cb(cb, cb_data)
        cb.answer.assert_called()
        # show_alert=True when empty
        assert cb.answer.call_args[1].get("show_alert") is True
