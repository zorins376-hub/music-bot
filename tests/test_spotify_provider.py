"""
Тесты для bot/services/spotify_provider.py
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestIsSpotifyUrl:
    def test_standard_url(self):
        from bot.services.spotify_provider import is_spotify_url
        assert is_spotify_url("https://open.spotify.com/track/6rqhFgbbKwnb9MLmUQDhG6") is True

    def test_intl_url(self):
        from bot.services.spotify_provider import is_spotify_url
        assert is_spotify_url("https://open.spotify.com/intl-ru/track/6rqhFgbbKwnb9MLmUQDhG6") is True

    def test_non_spotify_url(self):
        from bot.services.spotify_provider import is_spotify_url
        assert is_spotify_url("https://youtube.com/watch?v=abc") is False

    def test_plain_text(self):
        from bot.services.spotify_provider import is_spotify_url
        assert is_spotify_url("imagine dragons bones") is False

    def test_empty(self):
        from bot.services.spotify_provider import is_spotify_url
        assert is_spotify_url("") is False

    def test_album_url_rejected(self):
        from bot.services.spotify_provider import is_spotify_url
        assert is_spotify_url("https://open.spotify.com/album/6rqhFgbbKwnb9MLmUQDhG6") is False

    def test_playlist_url_rejected(self):
        from bot.services.spotify_provider import is_spotify_url
        assert is_spotify_url("https://open.spotify.com/playlist/37i9dQZF1DX4dyzvuaRJ0n") is False


class TestTrackToDict:
    def test_valid_track(self):
        from bot.services.spotify_provider import _track_to_dict

        track = {
            "id": "abc123def456ghi789jk00",
            "name": "Bones",
            "artists": [{"name": "Imagine Dragons"}],
            "duration_ms": 210000,
        }
        result = _track_to_dict(track)
        assert result is not None
        assert result["video_id"] == "sp_abc123def456ghi789jk00"
        assert result["spotify_id"] == "abc123def456ghi789jk00"
        assert result["title"] == "Bones"
        assert result["uploader"] == "Imagine Dragons"
        assert result["duration"] == 210
        assert result["source"] == "spotify"
        assert result["yt_query"] == "Imagine Dragons - Bones"

    def test_multiple_artists(self):
        from bot.services.spotify_provider import _track_to_dict

        track = {
            "id": "multiartist00000000000",
            "name": "Collab Song",
            "artists": [{"name": "Artist1"}, {"name": "Artist2"}],
            "duration_ms": 180000,
        }
        result = _track_to_dict(track)
        assert result is not None
        assert result["uploader"] == "Artist1, Artist2"

    def test_missing_name_returns_none(self):
        from bot.services.spotify_provider import _track_to_dict

        track = {"id": "noid00000000000000000", "name": "", "artists": [{"name": "A"}], "duration_ms": 180000}
        assert _track_to_dict(track) is None

    def test_no_artists_returns_none(self):
        from bot.services.spotify_provider import _track_to_dict

        track = {"id": "noart0000000000000000", "name": "Song", "artists": [], "duration_ms": 180000}
        assert _track_to_dict(track) is None

    def test_too_long_returns_none(self):
        from bot.services.spotify_provider import _track_to_dict
        from bot.config import settings

        track = {
            "id": "toolong000000000000000",
            "name": "Long Song",
            "artists": [{"name": "Artist"}],
            "duration_ms": (settings.MAX_DURATION + 10) * 1000,
        }
        assert _track_to_dict(track) is None

    def test_no_id_returns_none(self):
        from bot.services.spotify_provider import _track_to_dict

        track = {"id": "", "name": "Song", "artists": [{"name": "A"}], "duration_ms": 180000}
        assert _track_to_dict(track) is None

    def test_duration_format(self):
        from bot.services.spotify_provider import _track_to_dict

        track = {
            "id": "durfmt000000000000000",
            "name": "Song",
            "artists": [{"name": "A"}],
            "duration_ms": 195000,  # 3:15
        }
        result = _track_to_dict(track)
        assert result["duration_fmt"] == "3:15"
        assert result["duration"] == 195


class TestFmtDur:
    def test_formats(self):
        from bot.services.spotify_provider import _fmt_dur
        assert _fmt_dur(180000) == "3:00"
        assert _fmt_dur(195000) == "3:15"
        assert _fmt_dur(60000) == "1:00"
        assert _fmt_dur(5000) == "0:05"


class TestSearchSync:
    def test_returns_empty_without_client(self):
        from bot.services.spotify_provider import _search_sync
        with patch("bot.services.spotify_provider._get_client", return_value=None):
            result = _search_sync("test", 5)
        assert result == []

    def test_returns_tracks(self):
        from bot.services.spotify_provider import _search_sync

        mock_sp = MagicMock()
        mock_sp.search.return_value = {
            "tracks": {
                "items": [
                    {
                        "id": "t1_search_test_00000000",
                        "name": "Song One",
                        "artists": [{"name": "Artist One"}],
                        "duration_ms": 200000,
                    },
                    {
                        "id": "t2_search_test_00000000",
                        "name": "Song Two",
                        "artists": [{"name": "Artist Two"}],
                        "duration_ms": 180000,
                    },
                ]
            }
        }
        with patch("bot.services.spotify_provider._get_client", return_value=mock_sp):
            results = _search_sync("test query", 5)

        assert len(results) == 2
        assert results[0]["title"] == "Song One"
        assert results[1]["title"] == "Song Two"

    def test_respects_limit(self):
        from bot.services.spotify_provider import _search_sync

        mock_sp = MagicMock()
        items = [
            {
                "id": f"lim_test_{i:018d}",
                "name": f"Song {i}",
                "artists": [{"name": f"Art {i}"}],
                "duration_ms": 180000,
            }
            for i in range(10)
        ]
        mock_sp.search.return_value = {"tracks": {"items": items}}

        with patch("bot.services.spotify_provider._get_client", return_value=mock_sp):
            results = _search_sync("query", 3)

        assert len(results) == 3

    def test_returns_empty_on_exception(self):
        from bot.services.spotify_provider import _search_sync

        mock_sp = MagicMock()
        mock_sp.search.side_effect = Exception("API error")

        with patch("bot.services.spotify_provider._get_client", return_value=mock_sp):
            result = _search_sync("query", 5)

        assert result == []


class TestResolveSync:
    def test_valid_url(self):
        from bot.services.spotify_provider import _resolve_sync

        mock_sp = MagicMock()
        mock_sp.track.return_value = {
            "id": "resolve_test_0000000000",
            "name": "Resolved Song",
            "artists": [{"name": "Resolved Artist"}],
            "duration_ms": 200000,
        }

        with patch("bot.services.spotify_provider._get_client", return_value=mock_sp):
            result = _resolve_sync("https://open.spotify.com/track/6rqhFgbbKwnb9MLmUQDhG6")

        assert result is not None
        assert result["title"] == "Resolved Song"

    def test_invalid_url_returns_none(self):
        from bot.services.spotify_provider import _resolve_sync
        assert _resolve_sync("https://youtube.com/watch?v=abc") is None

    def test_no_client_returns_none(self):
        from bot.services.spotify_provider import _resolve_sync
        with patch("bot.services.spotify_provider._get_client", return_value=None):
            result = _resolve_sync("https://open.spotify.com/track/6rqhFgbbKwnb9MLmUQDhG6")
        assert result is None

    def test_api_error_returns_none(self):
        from bot.services.spotify_provider import _resolve_sync

        mock_sp = MagicMock()
        mock_sp.track.side_effect = Exception("API error")

        with patch("bot.services.spotify_provider._get_client", return_value=mock_sp):
            result = _resolve_sync("https://open.spotify.com/track/6rqhFgbbKwnb9MLmUQDhG6")
        assert result is None

    def test_intl_url(self):
        from bot.services.spotify_provider import _resolve_sync

        mock_sp = MagicMock()
        mock_sp.track.return_value = {
            "id": "intl_resolve_test_00000",
            "name": "IntlSong",
            "artists": [{"name": "IntlArtist"}],
            "duration_ms": 180000,
        }

        with patch("bot.services.spotify_provider._get_client", return_value=mock_sp):
            result = _resolve_sync("https://open.spotify.com/intl-ru/track/6rqhFgbbKwnb9MLmUQDhG6")

        assert result is not None


@pytest.mark.asyncio
class TestSearchSpotifyAsync:
    async def test_returns_list(self):
        from bot.services.spotify_provider import search_spotify

        expected = [{"video_id": "sp_1", "title": "Song", "source": "spotify"}]
        with patch("bot.services.spotify_provider._search_sync", return_value=expected):
            result = await search_spotify("test", 5)
        assert result == expected


@pytest.mark.asyncio
class TestResolveSpotifyUrlAsync:
    async def test_returns_dict_or_none(self):
        from bot.services.spotify_provider import resolve_spotify_url

        expected = {"video_id": "sp_1", "title": "Song"}
        with patch("bot.services.spotify_provider._resolve_sync", return_value=expected):
            result = await resolve_spotify_url("https://open.spotify.com/track/6rqhFgbbKwnb9MLmUQDhG6")
        assert result == expected
