"""
Тесты для bot/services/vk_provider.py
"""
import pytest
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
class TestSearchVk:
    async def test_returns_empty_without_token(self):
        """Без VK_TOKEN возвращает []."""
        from bot.services import vk_provider

        with patch("bot.services.vk_provider.settings") as mock_settings:
            mock_settings.VK_TOKEN = None
            mock_settings.MAX_DURATION = 600
            result = await vk_provider.search_vk("test")
            assert result == []

    async def test_returns_empty_without_library(self):
        with patch("bot.services.vk_provider._get_vk_audio", return_value=None):
            from bot.services.vk_provider import search_vk
            result = await search_vk("test query")
            assert result == []

    async def test_returns_tracks_from_api(self):
        tracks = [
            {
                "artist": "Bones",
                "title": "WhereTreesMeetRoots",
                "duration": 180,
                "url": "https://vk.com/audio_track",
                "owner_id": 123,
                "id": 456,
            }
        ]
        # Патчим _search_vk_sync напрямую — он работает в threadpool
        # Также задаём VK_TOKEN чтобы search_vk не вернул [] сразу
        expected = [
            {
                "video_id": "vk_123_456",
                "vk_url": "https://vk.com/audio_track",
                "title": "WhereTreesMeetRoots",
                "uploader": "Bones",
                "duration": 180,
                "duration_fmt": "3:00",
                "source": "vk",
            }
        ]
        with patch("bot.services.vk_provider._search_vk_sync", return_value=expected), \
             patch("bot.services.vk_provider.settings") as mock_settings:
            mock_settings.VK_TOKEN = "fake_vk_token"
            from bot.services.vk_provider import search_vk
            results = await search_vk("Bones", limit=5)

        assert len(results) == 1
        assert results[0]["source"] == "vk"
        assert results[0]["title"] == "WhereTreesMeetRoots"
        assert results[0]["uploader"] == "Bones"
        assert "vk_url" in results[0]
        assert results[0]["video_id"].startswith("vk_")

    async def test_filters_out_tracks_without_url(self):
        """Formatting filters out unusable VK tracks."""
        from bot.services.vk_provider import _format_vk_results

        tracks = [
            {"artist": "Artist", "title": "Track", "duration": 180, "url": "", "owner_id": 1, "id": 1},
            {"artist": "Artist2", "title": "Track2", "duration": 200, "url": "https://real.url", "owner_id": 2, "id": 2},
        ]

        results = _format_vk_results(tracks, limit=10)

        assert len(results) == 1
        assert results[0]["title"] == "Track2"

    async def test_filters_too_long_tracks(self):
        from bot.config import settings
        from bot.services.vk_provider import _format_vk_results

        tracks = [
            {
                "artist": "Art", "title": "Long", "duration": settings.MAX_DURATION + 1,
                "url": "https://url.com", "owner_id": 1, "id": 1
            },
            {
                "artist": "Art", "title": "Short", "duration": 180,
                "url": "https://url2.com", "owner_id": 2, "id": 2
            },
        ]

        results = _format_vk_results(tracks, limit=10)

        assert len(results) == 1
        assert results[0]["title"] == "Short"

    async def test_respects_limit(self):
        from bot.services.vk_provider import _format_vk_results

        tracks = [
            {"artist": f"Art{i}", "title": f"Track{i}", "duration": 180,
             "url": f"https://url{i}.com", "owner_id": i, "id": i}
            for i in range(10)
        ]

        results = _format_vk_results(tracks, limit=3)

        assert len(results) == 3

    async def test_uses_direct_api_before_parser(self):
        from bot.services import vk_provider

        session = MagicMock()
        session.method.return_value = {
            "count": 1,
            "items": [{
                "artist": "Direct",
                "title": "Track",
                "duration": 180,
                "url": "https://vk.com/audio_direct",
                "owner_id": 10,
                "id": 20,
            }],
        }
        parser = MagicMock()

        with patch("bot.services.vk_provider._get_vk_session", return_value=session), \
             patch("bot.services.vk_provider._get_vk_audio", return_value=parser):
            results = vk_provider._search_vk_sync("direct", limit=5)

        assert results[0]["video_id"] == "vk_10_20"
        parser.search.assert_not_called()

    async def test_direct_api_accepts_old_list_shape(self):
        from bot.services import vk_provider

        session = MagicMock()
        session.method.return_value = [
            1,
            {
                "artist": "OldShape",
                "title": "Track",
                "duration": 181,
                "url": "https://vk.com/audio_old",
                "owner_id": 11,
                "id": 21,
            },
        ]

        with patch("bot.services.vk_provider._get_vk_session", return_value=session):
            results = vk_provider._search_vk_sync("old shape", limit=5)

        assert len(results) == 1
        assert results[0]["title"] == "Track"

    async def test_web_search_empty_payload_returns_empty(self):
        from bot.services import vk_provider

        class FakeResponse:
            text = '<!--{"payload":[0,[]]}'

        fake_audio = MagicMock()
        fake_audio.user_id = 123
        fake_audio.convert_m3u8_links = True
        fake_audio._vk.http.post.return_value = FakeResponse()

        vk_api_mod = types.ModuleType("vk_api")
        audio_mod = types.ModuleType("vk_api.audio")
        audio_mod.scrap_ids = lambda value: []
        audio_mod.scrap_tracks = lambda *args, **kwargs: []

        with patch("bot.services.vk_provider._get_vk_audio", return_value=fake_audio), \
             patch.dict(sys.modules, {"vk_api": vk_api_mod, "vk_api.audio": audio_mod}):
            assert vk_provider._search_vk_web_sync("empty", limit=5) == []

    async def test_returns_empty_on_exception(self):
        mock_audio = MagicMock()
        mock_audio.search.side_effect = Exception("VK API error")

        with patch("bot.services.vk_provider._get_vk_audio", return_value=mock_audio):
            from bot.services.vk_provider import search_vk
            result = await search_vk("query")

        assert result == []


class TestFmtDur:
    def test_format_duration(self):
        from bot.services.vk_provider import _fmt_dur
        assert _fmt_dur(180) == "3:00"
        assert _fmt_dur(195) == "3:15"
        assert _fmt_dur(60) == "1:00"
        assert _fmt_dur(5) == "0:05"
