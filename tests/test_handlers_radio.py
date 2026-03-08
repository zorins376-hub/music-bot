"""Tests for bot/handlers/radio.py — live channels, automix, channel capture."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import make_callback, make_message


def _make_user(lang="ru"):
    u = MagicMock()
    u.id = 1
    u.language = lang
    return u


# ── _channel_label ───────────────────────────────────────────────────────

class TestChannelLabel:
    @patch("bot.handlers.radio.settings")
    def test_tequila_channel(self, mock_settings):
        from bot.handlers.radio import _channel_label
        mock_settings.TEQUILA_CHANNEL = "-1001234"
        mock_settings.FULLMOON_CHANNEL = "-1005678"
        assert _channel_label(-1001234) == "tequila"

    @patch("bot.handlers.radio.settings")
    def test_fullmoon_channel(self, mock_settings):
        from bot.handlers.radio import _channel_label
        mock_settings.TEQUILA_CHANNEL = "-1001234"
        mock_settings.FULLMOON_CHANNEL = "-1005678"
        assert _channel_label(-1005678) == "fullmoon"

    @patch("bot.handlers.radio.settings")
    def test_unknown_channel(self, mock_settings):
        from bot.handlers.radio import _channel_label
        mock_settings.TEQUILA_CHANNEL = "-1001234"
        mock_settings.FULLMOON_CHANNEL = "-1005678"
        assert _channel_label(-1009999) is None

    @patch("bot.handlers.radio.settings")
    def test_string_channel_id(self, mock_settings):
        from bot.handlers.radio import _channel_label
        mock_settings.TEQUILA_CHANNEL = "@tequila_ch"
        mock_settings.FULLMOON_CHANNEL = "@fullmoon_ch"
        # string comparison: str(chat_id) == "@tequila_ch".lstrip("@")
        assert _channel_label("tequila_ch") == "tequila"


# ── _get_current_track ───────────────────────────────────────────────────

class TestGetCurrentTrack:
    @pytest.mark.asyncio
    @patch("bot.handlers.radio.cache")
    async def test_returns_track_data(self, mock_cache):
        from bot.handlers.radio import _get_current_track
        import json
        track = {"artist": "Test", "title": "Song"}
        mock_cache.redis = AsyncMock()
        mock_cache.redis.get = AsyncMock(return_value=json.dumps(track))
        result = await _get_current_track("tequila")
        assert result["artist"] == "Test"

    @pytest.mark.asyncio
    @patch("bot.handlers.radio.cache")
    async def test_returns_none_when_empty(self, mock_cache):
        from bot.handlers.radio import _get_current_track
        mock_cache.redis = AsyncMock()
        mock_cache.redis.get = AsyncMock(return_value=None)
        result = await _get_current_track("tequila")
        assert result is None


# ── handle_tequila_live / handle_fullmoon_live ───────────────────────────

class TestLiveHandlers:
    @pytest.mark.asyncio
    @patch("bot.handlers.radio._send_live_menu", new_callable=AsyncMock)
    @patch("bot.handlers.radio.get_or_create_user", new_callable=AsyncMock)
    async def test_tequila_live(self, mock_goc, mock_menu):
        from bot.handlers.radio import handle_tequila_live
        mock_goc.return_value = _make_user()
        cb = make_callback("radio:tequila")
        await handle_tequila_live(cb)
        cb.answer.assert_called()
        mock_menu.assert_called_once()

    @pytest.mark.asyncio
    @patch("bot.handlers.radio._send_live_menu", new_callable=AsyncMock)
    @patch("bot.handlers.radio.get_or_create_user", new_callable=AsyncMock)
    async def test_fullmoon_live(self, mock_goc, mock_menu):
        from bot.handlers.radio import handle_fullmoon_live
        mock_goc.return_value = _make_user()
        cb = make_callback("radio:fullmoon")
        await handle_fullmoon_live(cb)
        cb.answer.assert_called()
        mock_menu.assert_called_once()


# ── handle_channel_post ──────────────────────────────────────────────────

class TestChannelPost:
    @pytest.mark.asyncio
    @patch("bot.handlers.radio.upsert_track", new_callable=AsyncMock)
    @patch("bot.handlers.radio._channel_label", return_value="tequila")
    async def test_audio_post_captured(self, mock_label, mock_upsert):
        from bot.handlers.radio import handle_channel_post
        msg = make_message()
        msg.audio = MagicMock()
        msg.audio.title = "Track Title"
        msg.audio.file_name = "track.mp3"
        msg.audio.performer = "DJ"
        msg.audio.duration = 180
        msg.audio.file_id = "fid_abc"
        msg.chat = MagicMock()
        msg.chat.id = -1001234
        msg.message_id = 42
        await handle_channel_post(msg)
        mock_upsert.assert_called_once()

    @pytest.mark.asyncio
    @patch("bot.handlers.radio._channel_label", return_value="tequila")
    async def test_non_audio_post_ignored(self, mock_label):
        from bot.handlers.radio import handle_channel_post
        msg = make_message()
        msg.audio = None
        await handle_channel_post(msg)
        # No crash, no action

    @pytest.mark.asyncio
    @patch("bot.handlers.radio._channel_label", return_value=None)
    async def test_unknown_channel_ignored(self, mock_label):
        from bot.handlers.radio import handle_channel_post
        msg = make_message()
        msg.audio = MagicMock()
        msg.chat = MagicMock()
        msg.chat.id = -100999
        await handle_channel_post(msg)
        # No upsert called


# ── handle_automix ───────────────────────────────────────────────────────

class TestHandleAutomix:
    @pytest.mark.asyncio
    @patch("bot.handlers.radio.async_session")
    @patch("bot.handlers.radio.get_or_create_user", new_callable=AsyncMock)
    async def test_shows_genre_keyboard(self, mock_goc, mock_sess):
        from bot.handlers.radio import handle_automix
        mock_goc.return_value = _make_user()

        result_mock = MagicMock()
        result_mock.all.return_value = []
        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)
        mock_sess.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_sess.return_value.__aexit__ = AsyncMock(return_value=False)

        cb = make_callback("radio:automix")
        await handle_automix(cb)
        cb.answer.assert_called()
        cb.message.answer.assert_called()


# ── MixCb / LiveCb callback data ────────────────────────────────────────

class TestCallbackData:
    def test_mix_cb_pack(self):
        from bot.handlers.radio import MixCb
        cb = MixCb(act="go", genre="rock")
        packed = cb.pack()
        unpacked = MixCb.unpack(packed)
        assert unpacked.genre == "rock"

    def test_live_cb_pack(self):
        from bot.handlers.radio import LiveCb
        cb = LiveCb(act="play", ch="tequila")
        packed = cb.pack()
        unpacked = LiveCb.unpack(packed)
        assert unpacked.ch == "tequila"

    def test_live_cb_shuf(self):
        from bot.handlers.radio import LiveCb
        cb = LiveCb(act="shuf", ch="fullmoon")
        packed = cb.pack()
        unpacked = LiveCb.unpack(packed)
        assert unpacked.act == "shuf"


# ── Handle whats playing ────────────────────────────────────────────────

class TestWhatsPlaying:
    @pytest.mark.asyncio
    @patch("bot.handlers.radio._get_current_track", new_callable=AsyncMock)
    @patch("bot.handlers.radio.get_or_create_user", new_callable=AsyncMock)
    async def test_nothing_playing(self, mock_goc, mock_track):
        from bot.handlers.radio import handle_whats_playing
        mock_goc.return_value = _make_user()
        mock_track.return_value = None
        msg = make_message("что играет")
        msg.text = "что играет"
        await handle_whats_playing(msg)
        msg.answer.assert_called()

    @pytest.mark.asyncio
    @patch("bot.handlers.radio._get_current_track", new_callable=AsyncMock)
    @patch("bot.handlers.radio.get_or_create_user", new_callable=AsyncMock)
    async def test_track_playing(self, mock_goc, mock_track):
        from bot.handlers.radio import handle_whats_playing
        mock_goc.return_value = _make_user()
        mock_track.side_effect = [
            {"artist": "DJ", "title": "Beat"},  # tequila
            None,  # fullmoon
        ]
        msg = make_message("что играет")
        msg.text = "что играет"
        await handle_whats_playing(msg)
        msg.answer.assert_called()
