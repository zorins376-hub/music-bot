"""
Тесты для bot/services/yandex_provider.py
"""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
class TestSearchYandex:
    async def test_returns_empty_without_token(self):
        """Без токена возвращает [] без исключения."""
        with patch("bot.services.yandex_provider._next_token", return_value=None):
            from bot.services.yandex_provider import search_yandex
            result = await search_yandex("test query")
            assert result == []

    async def test_returns_empty_without_library(self):
        """Если yandex-music не установлен — возвращает []."""
        with patch("bot.services.yandex_provider._next_token", return_value="fake_token"), \
             patch.dict("sys.modules", {"yandex_music": None}):
            from bot.services.yandex_provider import search_yandex
            result = await search_yandex("test query")
            assert result == []

    async def test_returns_empty_on_client_init_failure(self):
        """Если клиент не инициализировался — возвращает []."""
        with patch("bot.services.yandex_provider._next_token", return_value="fake_token"), \
             patch("bot.services.yandex_provider._get_client", new_callable=AsyncMock, return_value=None):
            from bot.services.yandex_provider import search_yandex
            result = await search_yandex("test query")
            assert result == []

    async def test_returns_tracks_from_search(self):
        """Успешный поиск возвращает список треков с нужными полями."""
        mock_artist = MagicMock()
        mock_artist.name = "Imagine Dragons"  # name — атрибут, не аргумент MagicMock
        mock_track = MagicMock()
        mock_track.id = 12345
        mock_track.title = "Bones"
        mock_track.artists = [mock_artist]
        mock_track.duration_ms = 210000  # 3:30
        mock_track.available = True

        mock_search_result = MagicMock()
        mock_search_result.tracks = MagicMock()
        mock_search_result.tracks.results = [mock_track]

        mock_client = AsyncMock()
        mock_client.search = AsyncMock(return_value=mock_search_result)

        with patch("bot.services.yandex_provider._next_token", return_value="token"), \
             patch("bot.services.yandex_provider._get_client", new_callable=AsyncMock, return_value=mock_client):
            from bot.services.yandex_provider import search_yandex
            results = await search_yandex("Bones")

        assert len(results) >= 1
        track = results[0]
        assert track["source"] == "yandex"
        assert track["ym_track_id"] == 12345
        assert track["video_id"] == "ym_12345"
        assert "title" in track
        assert "uploader" in track
        assert "duration" in track

    async def test_respects_limit(self):
        """Не возвращает больше треков чем limit."""
        mock_tracks = []
        for i in range(10):
            t = MagicMock()
            t.id = i
            t.title = f"Track {i}"
            mock_artist = MagicMock()
            mock_artist.name = f"Artist {i}"
            t.artists = [mock_artist]
            t.duration_ms = 180000
            t.available = True
            mock_tracks.append(t)

        mock_search_result = MagicMock()
        mock_search_result.tracks = MagicMock()
        mock_search_result.tracks.results = mock_tracks

        mock_client = AsyncMock()
        mock_client.search = AsyncMock(return_value=mock_search_result)

        with patch("bot.services.yandex_provider._next_token", return_value="token"), \
             patch("bot.services.yandex_provider._get_client", new_callable=AsyncMock, return_value=mock_client):
            from bot.services.yandex_provider import search_yandex
            results = await search_yandex("query", limit=3)

        assert len(results) <= 3

    async def test_returns_empty_on_exception(self):
        """При любой ошибке возвращает [] без исключения."""
        mock_client = AsyncMock()
        mock_client.search = AsyncMock(side_effect=Exception("API error"))

        with patch("bot.services.yandex_provider._next_token", return_value="token"), \
             patch("bot.services.yandex_provider._get_client", new_callable=AsyncMock, return_value=mock_client):
            from bot.services.yandex_provider import search_yandex
            result = await search_yandex("query")

        assert result == []


@pytest.mark.asyncio
class TestDownloadYandex:
    async def test_raises_without_token(self, tmp_path):
        with patch("bot.services.yandex_provider._next_token", return_value=None):
            from bot.services.yandex_provider import download_yandex
            with pytest.raises(RuntimeError, match="No Yandex token"):
                await download_yandex(12345, tmp_path / "out.mp3")

    async def test_raises_on_client_failure(self, tmp_path):
        with patch("bot.services.yandex_provider._next_token", return_value="token"), \
             patch("bot.services.yandex_provider._get_client", new_callable=AsyncMock, return_value=None):
            from bot.services.yandex_provider import download_yandex
            with pytest.raises(RuntimeError, match="unavailable"):
                await download_yandex(12345, tmp_path / "out.mp3")

    async def test_raises_if_track_not_found(self, tmp_path):
        mock_client = AsyncMock()
        mock_client.tracks = AsyncMock(return_value=[])

        with patch("bot.services.yandex_provider._next_token", return_value="token"), \
             patch("bot.services.yandex_provider._get_client", new_callable=AsyncMock, return_value=mock_client):
            from bot.services.yandex_provider import download_yandex
            with pytest.raises(RuntimeError, match="not found"):
                await download_yandex(12345, tmp_path / "out.mp3")

    async def test_download_success(self, tmp_path):
        """Успешное скачивание создаёт файл."""
        dest = tmp_path / "track.mp3"
        # Создаём фейковый файл (download_async должен его создать)
        mock_di = MagicMock()
        mock_di.codec = "mp3"
        mock_di.bitrate_in_kbps = 320
        mock_di.download_async = AsyncMock(side_effect=lambda path: Path(path).write_bytes(b"FAKEMP3" * 200))

        mock_track = MagicMock()
        mock_track.get_download_info_async = AsyncMock(return_value=[mock_di])

        mock_client = AsyncMock()
        mock_client.tracks = AsyncMock(return_value=[mock_track])

        with patch("bot.services.yandex_provider._next_token", return_value="token"), \
             patch("bot.services.yandex_provider._get_client", new_callable=AsyncMock, return_value=mock_client):
            from bot.services.yandex_provider import download_yandex
            result = await download_yandex(12345, dest, bitrate=320)

        assert result == dest
        assert dest.exists()
        assert dest.stat().st_size > 1024


class TestTrackToDict:
    def test_valid_track(self):
        from bot.services.yandex_provider import _track_to_dict
        mock_artist = MagicMock()
        mock_artist.name = "Test Artist"
        mock_track = MagicMock()
        mock_track.id = 999
        mock_track.title = "Test Song"
        mock_track.artists = [mock_artist]
        mock_track.duration_ms = 200000

        result = _track_to_dict(mock_track)
        assert result is not None
        assert result["source"] == "yandex"
        assert result["ym_track_id"] == 999
        assert result["title"] == "Test Song"

    def test_missing_title_returns_none(self):
        from bot.services.yandex_provider import _track_to_dict
        mock_track = MagicMock()
        mock_track.id = 1
        mock_track.title = ""
        mock_track.artists = [MagicMock(name="Artist")]
        mock_track.duration_ms = 180000

        result = _track_to_dict(mock_track)
        assert result is None

    def test_too_long_track_filtered(self):
        from bot.services.yandex_provider import _track_to_dict
        from bot.config import settings
        mock_track = MagicMock()
        mock_track.id = 2
        mock_track.title = "Very Long Track"
        mock_track.artists = [MagicMock(name="Artist")]
        mock_track.duration_ms = (settings.MAX_DURATION + 10) * 1000

        result = _track_to_dict(mock_track)
        assert result is None
