"""Tests for the deep background crawler."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.services.deep_crawler import (
    _collect_all_genre_ids,
    _extract_spotify_track,
    _is_done,
    _mark_done,
    _enqueue,
    _dequeue_batch,
    _mem_done,
    _mem_queue,
    get_crawler_stats,
)


@pytest.fixture(autouse=True)
def _reset_mem_state():
    """Reset in-memory crawler state between tests."""
    for k in _mem_done:
        _mem_done[k].clear()
    for k in _mem_queue:
        _mem_queue[k].clear()
    yield
    for k in _mem_done:
        _mem_done[k].clear()
    for k in _mem_queue:
        _mem_queue[k].clear()


# ── Queue helpers ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mark_done_and_is_done():
    with patch("bot.services.deep_crawler._get_redis", return_value=None):
        assert not await _is_done("ym:artists", "123")
        await _mark_done("ym:artists", "123")
        assert await _is_done("ym:artists", "123")


@pytest.mark.asyncio
async def test_enqueue_skips_done():
    with patch("bot.services.deep_crawler._get_redis", return_value=None):
        await _mark_done("sp:artists", "abc")
        await _enqueue("sp:artists", "abc")
        batch = await _dequeue_batch("sp:artists", 10)
        assert "abc" not in batch


@pytest.mark.asyncio
async def test_enqueue_and_dequeue():
    with patch("bot.services.deep_crawler._get_redis", return_value=None):
        await _enqueue("ym:artists", "1")
        await _enqueue("ym:artists", "2")
        await _enqueue("ym:artists", "3")
        batch = await _dequeue_batch("ym:artists", 2)
        assert len(batch) == 2
        assert batch == ["1", "2"]
        batch2 = await _dequeue_batch("ym:artists", 5)
        assert batch2 == ["3"]


# ── Genre collection ──────────────────────────────────────────────────────

def test_collect_all_genre_ids():
    sub = MagicMock()
    sub.id = "alternative"
    sub.title = "Альтернатива"
    sub.sub_genres = []

    genre = MagicMock()
    genre.id = "rock"
    genre.title = "Рок"
    genre.sub_genres = [sub]

    genre2 = MagicMock()
    genre2.id = "pop"
    genre2.title = "Поп"
    genre2.sub_genres = []

    result = _collect_all_genre_ids([genre, genre2])
    assert ("rock", "Рок") in result
    assert ("alternative", "Альтернатива") in result
    assert ("pop", "Поп") in result
    assert len(result) == 3


def test_collect_all_genre_ids_deep_nesting():
    """Three levels: rock → alternative → shoegaze."""
    shoegaze = MagicMock()
    shoegaze.id = "shoegaze"
    shoegaze.title = "Shoegaze"
    shoegaze.sub_genres = []

    alt = MagicMock()
    alt.id = "alternative"
    alt.title = "Alternative"
    alt.sub_genres = [shoegaze]

    rock = MagicMock()
    rock.id = "rock"
    rock.title = "Rock"
    rock.sub_genres = [alt]

    result = _collect_all_genre_ids([rock])
    assert len(result) == 3
    ids = [r[0] for r in result]
    assert ids == ["rock", "alternative", "shoegaze"]


# ── Spotify track extraction ─────────────────────────────────────────────

def test_extract_spotify_track():
    sp = MagicMock()
    artist_data = {"genres": ["pop", "dance pop"]}
    sp.artist.return_value = artist_data

    track = {
        "id": "abc123",
        "name": "Hit Song",
        "artists": [{"id": "art1", "name": "Singer"}],
        "duration_ms": 210000,
        "album": {
            "name": "Great Album",
            "release_date": "2024-03-15",
            "label": "Sony",
            "images": [{"url": "https://cover.jpg"}],
        },
        "external_ids": {"isrc": "USRC12300001"},
        "explicit": True,
        "popularity": 90,
    }

    # Clear cache
    from bot.services.track_indexer import _artist_genre_cache
    _artist_genre_cache.clear()

    result = _extract_spotify_track(sp, track)
    assert result is not None
    assert result["video_id"] == "sp_abc123"
    assert result["title"] == "Hit Song"
    assert result["artist"] == "Singer"
    assert result["duration"] == 210
    assert result["album"] == "Great Album"
    assert result["release_year"] == 2024
    assert result["label"] == "Sony"
    assert result["isrc"] == "USRC12300001"
    assert result["explicit"] is True
    assert result["popularity"] == 90
    assert result["genre"] == "pop"
    assert result["cover_url"] == "https://cover.jpg"

    _artist_genre_cache.clear()


def test_extract_spotify_track_no_id():
    sp = MagicMock()
    result = _extract_spotify_track(sp, {"name": "Song", "id": ""})
    assert result is None


# ── Deep crawl functions ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deep_crawl_yandex_no_token():
    with patch("bot.services.deep_crawler.settings") as mock_settings:
        mock_settings.YANDEX_MUSIC_TOKEN = ""
        from bot.services.deep_crawler import deep_crawl_yandex
        result = await deep_crawl_yandex()
        assert result == 0


@pytest.mark.asyncio
async def test_deep_crawl_spotify_no_creds():
    with patch("bot.services.deep_crawler.settings") as mock_settings:
        mock_settings.SPOTIFY_CLIENT_ID = ""
        mock_settings.SPOTIFY_CLIENT_SECRET = ""
        from bot.services.deep_crawler import deep_crawl_spotify
        result = await deep_crawl_spotify()
        assert result == 0


@pytest.mark.asyncio
async def test_get_crawler_stats():
    with patch("bot.services.deep_crawler._get_redis", return_value=None):
        await _mark_done("ym:artists", "1")
        await _mark_done("ym:artists", "2")
        await _enqueue("sp:artists", "x")
        stats = await get_crawler_stats()
        assert stats["yandex"]["artists_done"] == 2
        assert stats["spotify"]["artists_queued"] == 1
