"""
Тесты для bot/services/vk_provider.py
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
class TestSearchVk:
    async def test_returns_empty_without_token(self):
        """Без VK_TOKEN возвращает []."""
        with patch("bot.config.settings") as mock_settings:
            mock_settings.VK_TOKEN = None
            mock_settings.MAX_DURATION = 600
            from bot.services.vk_provider import search_vk
            result = await search_vk("test")
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
        """_search_vk_sync уже фильтрует, тестируем логику синхронной функции."""
        from bot.services.vk_provider import _search_vk_sync

        mock_audio = MagicMock()
        mock_audio.search.return_value = [
            {"artist": "Artist", "title": "Track", "duration": 180, "url": "", "owner_id": 1, "id": 1},
            {"artist": "Artist2", "title": "Track2", "duration": 200, "url": "https://real.url", "owner_id": 2, "id": 2},
        ]

        with patch("bot.services.vk_provider._get_vk_audio", return_value=mock_audio):
            results = _search_vk_sync("test", limit=10)

        assert len(results) == 1
        assert results[0]["title"] == "Track2"

    async def test_filters_too_long_tracks(self):
        from bot.config import settings
        from bot.services.vk_provider import _search_vk_sync

        mock_audio = MagicMock()
        mock_audio.search.return_value = [
            {
                "artist": "Art", "title": "Long", "duration": settings.MAX_DURATION + 1,
                "url": "https://url.com", "owner_id": 1, "id": 1
            },
            {
                "artist": "Art", "title": "Short", "duration": 180,
                "url": "https://url2.com", "owner_id": 2, "id": 2
            },
        ]

        with patch("bot.services.vk_provider._get_vk_audio", return_value=mock_audio):
            results = _search_vk_sync("test", limit=10)

        assert len(results) == 1
        assert results[0]["title"] == "Short"

    async def test_respects_limit(self):
        from bot.services.vk_provider import _search_vk_sync

        mock_audio = MagicMock()
        mock_audio.search.return_value = [
            {"artist": f"Art{i}", "title": f"Track{i}", "duration": 180,
             "url": f"https://url{i}.com", "owner_id": i, "id": i}
            for i in range(10)
        ]

        with patch("bot.services.vk_provider._get_vk_audio", return_value=mock_audio):
            results = _search_vk_sync("query", limit=3)

        assert len(results) == 3

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
