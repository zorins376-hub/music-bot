"""Tests for the background track indexer."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.services.track_indexer import (
    _detect_language,
    _extract_yandex_album_meta,
    _index_track_list,
    index_chart_tracks,
    _yandex_tracks_to_dicts,
)


@pytest.fixture
def sample_tracks():
    return [
        {
            "video_id": "ym_12345",
            "title": "Тестовая Песня",
            "artist": "Тест Артист",
            "duration": 200,
            "cover_url": "https://example.com/cover.jpg",
            "source": "yandex",
            "genre": "pop",
            "album": "Альбом",
            "release_year": 2024,
            "label": "Universal",
            "language": "ru",
        },
        {
            "video_id": "dQw4w9WgXcQ",
            "title": "Never Gonna Give You Up",
            "artist": "Rick Astley",
            "duration": 213,
            "cover_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
            "source": "youtube",
        },
        {
            "video_id": "sp_abc123",
            "title": "Spotify Track",
            "artist": "Spotify Artist",
            "duration": 180,
            "cover_url": "https://i.scdn.co/image/abc",
            "source": "spotify",
            "genre": "dance pop",
            "album": "Greatest Hits",
            "release_year": 2023,
            "isrc": "USRC12345678",
            "explicit": True,
            "popularity": 85,
            "language": "en",
        },
    ]


@pytest.mark.asyncio
async def test_index_track_list(db_session, sample_tracks):
    """Test that _index_track_list upserts tracks with full metadata."""
    with patch("bot.services.track_indexer.upsert_track", new_callable=AsyncMock) as mock_upsert:
        mock_upsert.return_value = MagicMock(id=1)
        count = await _index_track_list(sample_tracks)
        assert count == 3
        assert mock_upsert.call_count == 3

        # Verify first call (Yandex) — all metadata fields
        first_call = mock_upsert.call_args_list[0]
        assert first_call.kwargs["source_id"] == "ym_12345"
        assert first_call.kwargs["cover_url"] == "https://example.com/cover.jpg"
        assert first_call.kwargs["genre"] == "pop"
        assert first_call.kwargs["album"] == "Альбом"
        assert first_call.kwargs["release_year"] == 2024
        assert first_call.kwargs["label"] == "Universal"
        assert first_call.kwargs["language"] == "ru"

        # Verify third call (Spotify) — ISRC, explicit, popularity
        third_call = mock_upsert.call_args_list[2]
        assert third_call.kwargs["source_id"] == "sp_abc123"
        assert third_call.kwargs["isrc"] == "USRC12345678"
        assert third_call.kwargs["explicit"] is True
        assert third_call.kwargs["popularity"] == 85
        assert third_call.kwargs["genre"] == "dance pop"


@pytest.mark.asyncio
async def test_index_track_list_skips_no_video_id():
    """Tracks without video_id are skipped."""
    tracks = [{"title": "No ID", "artist": "Test"}]
    with patch("bot.services.track_indexer.upsert_track", new_callable=AsyncMock) as mock_upsert:
        count = await _index_track_list(tracks)
        assert count == 0
        mock_upsert.assert_not_called()


@pytest.mark.asyncio
async def test_index_track_list_skips_no_title():
    """Tracks without title are skipped."""
    tracks = [{"video_id": "abc123", "artist": "Test"}]
    with patch("bot.services.track_indexer.upsert_track", new_callable=AsyncMock) as mock_upsert:
        count = await _index_track_list(tracks)
        assert count == 0
        mock_upsert.assert_not_called()


@pytest.mark.asyncio
async def test_index_chart_tracks():
    """Test indexing from all chart sources."""
    fake_charts = {
        "shazam": [{"video_id": "abc", "title": "Pop Hit", "artist": "Star", "cover_url": "http://c.co/1"}],
        "youtube": [{"video_id": "xyz", "title": "YT Hit", "artist": "Creator", "cover_url": "http://c.co/2"}],
    }

    async def fake_get_chart(src):
        return fake_charts.get(src, [])

    with patch("bot.services.track_indexer.upsert_track", new_callable=AsyncMock) as mock_upsert:
        mock_upsert.return_value = MagicMock(id=1)
        with patch(
            "bot.handlers.charts._CHART_FETCHERS",
            {"shazam": AsyncMock(), "youtube": AsyncMock()},
        ):
            with patch("bot.handlers.charts._get_chart", side_effect=fake_get_chart):
                result = await index_chart_tracks()
                assert result == 2


@pytest.mark.asyncio
async def test_index_handles_upsert_error(sample_tracks):
    """Tracks that fail to upsert are skipped without crashing."""
    with patch("bot.services.track_indexer.upsert_track", new_callable=AsyncMock) as mock_upsert:
        mock_upsert.side_effect = Exception("DB error")
        count = await _index_track_list(sample_tracks)
        assert count == 0  # All failed


def test_yandex_tracks_to_dicts_with_full_metadata():
    """Convert Yandex SDK-like objects to dicts with full metadata."""
    track = MagicMock()
    track.title = "Ворона"
    track.id = 145463274
    artist = MagicMock()
    artist.name = "Кэнни"
    track.artists = [artist]
    track.duration_ms = 195000
    track.cover_uri = "avatars.yandex.net/get-music-content/123/%%"
    track.og_image = None
    track.track_id = None
    track.content_warning = None
    track.explicit = None

    # Album with genre, year, label
    album = MagicMock()
    album.title = "Мой Альбом"
    album.genre = "hip-hop"
    album.year = 2024
    album.cover_uri = None
    label = MagicMock()
    label.name = "Sony Music"
    album.labels = [label]
    track.albums = [album]

    item = MagicMock()
    item.track = track

    result = _yandex_tracks_to_dicts([item])
    assert len(result) == 1
    r = result[0]
    assert r["video_id"] == "ym_145463274"
    assert r["title"] == "Ворона"
    assert r["artist"] == "Кэнни"
    assert r["cover_url"] == "https://avatars.yandex.net/get-music-content/123/400x400"
    assert r["duration"] == 195
    assert r["album"] == "Мой Альбом"
    assert r["genre"] == "hip-hop"
    assert r["release_year"] == 2024
    assert r["label"] == "Sony Music"
    assert r["language"] == "ru"
    assert r["explicit"] is None  # no content_warning


def test_yandex_tracks_to_dicts_explicit_track():
    """Yandex track with content_warning → explicit=True."""
    track = MagicMock()
    track.title = "Explicit Song"
    track.id = 999
    artist = MagicMock()
    artist.name = "Artist"
    track.artists = [artist]
    track.duration_ms = 180000
    track.cover_uri = ""
    track.og_image = None
    track.track_id = None
    track.content_warning = "explicit"
    track.albums = []

    item = MagicMock()
    item.track = track

    result = _yandex_tracks_to_dicts([item])
    assert result[0]["explicit"] is True


def test_yandex_tracks_to_dicts_with_force_genre():
    """force_genre overrides album genre."""
    track = MagicMock()
    track.title = "Song"
    track.id = 111
    artist = MagicMock()
    artist.name = "Art"
    track.artists = [artist]
    track.duration_ms = 120000
    track.cover_uri = ""
    track.og_image = None
    track.track_id = None
    track.content_warning = None
    album = MagicMock()
    album.title = "Album"
    album.genre = "rock"
    album.year = 2020
    album.labels = []
    album.cover_uri = None
    track.albums = [album]

    item = MagicMock()
    item.track = track

    result = _yandex_tracks_to_dicts([item], force_genre="electronic")
    assert result[0]["genre"] == "electronic"


def test_yandex_tracks_to_dicts_with_album_meta():
    """album_meta fills missing fields when track has no album info."""
    track = MagicMock()
    track.title = "Track"
    track.id = 222
    artist = MagicMock()
    artist.name = "Singer"
    track.artists = [artist]
    track.duration_ms = 200000
    track.cover_uri = ""
    track.og_image = None
    track.track_id = None
    track.content_warning = None
    track.albums = []

    item = MagicMock()
    item.track = track

    album_meta = {
        "album": "Parent Album",
        "genre": "jazz",
        "release_year": 2022,
        "label": "Blue Note",
        "cover_url": "https://example.com/album_cover.jpg",
    }
    result = _yandex_tracks_to_dicts([item], album_meta=album_meta)
    r = result[0]
    assert r["album"] == "Parent Album"
    assert r["genre"] == "jazz"
    assert r["release_year"] == 2022
    assert r["label"] == "Blue Note"
    assert r["cover_url"] == "https://example.com/album_cover.jpg"


def test_extract_yandex_album_meta():
    """Extract album-level metadata from a Yandex Album object."""
    album = MagicMock()
    album.title = "Тестовый Альбом"
    album.genre = "pop"
    album.year = 2023
    label = MagicMock()
    label.name = "Warner"
    album.labels = [label]
    album.cover_uri = "avatars.yandex.net/get-music-content/456/%%"

    meta = _extract_yandex_album_meta(album)
    assert meta["album"] == "Тестовый Альбом"
    assert meta["genre"] == "pop"
    assert meta["release_year"] == 2023
    assert meta["label"] == "Warner"
    assert meta["cover_url"] == "https://avatars.yandex.net/get-music-content/456/400x400"


def test_detect_language_russian():
    assert _detect_language("Привет мир") == "ru"


def test_detect_language_english():
    assert _detect_language("Hello world") == "en"


def test_detect_language_mixed():
    """Dominant script wins."""
    assert _detect_language("Кэнни слушает Артиста") == "ru"


def test_detect_language_no_alpha():
    assert _detect_language("12345 !@#") is None


@pytest.mark.asyncio
async def test_track_model_has_all_fields(db_session):
    """Verify the Track model has all rich metadata fields."""
    from bot.models.track import Track
    for field in ("cover_url", "album", "genre", "release_year", "label",
                  "isrc", "explicit", "popularity", "language"):
        assert hasattr(Track, field), f"Track model missing field: {field}"


@pytest.mark.asyncio
async def test_upsert_track_with_full_metadata(db_session):
    """Test that Track model accepts all rich metadata fields."""
    from bot.models.track import Track
    track = Track(
        source_id="ym_999",
        title="Test",
        artist="Artist",
        cover_url="https://example.com/cover.jpg",
        album="Test Album",
        genre="rock",
        release_year=2024,
        label="Universal",
        isrc="USRC17000001",
        explicit=True,
        popularity=75,
        language="en",
    )
    assert track.cover_url == "https://example.com/cover.jpg"
    assert track.album == "Test Album"
    assert track.genre == "rock"
    assert track.release_year == 2024
    assert track.label == "Universal"
    assert track.isrc == "USRC17000001"
    assert track.explicit is True
    assert track.popularity == 75
    assert track.language == "en"
