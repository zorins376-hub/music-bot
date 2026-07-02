"""Tests for bot/services/search_memory.py — learn correct track per query."""
import fakeredis.aioredis
import pytest


@pytest.fixture
def _fake_redis():
    import bot.services.cache as c
    prev = c.cache._redis
    c.cache._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield
    c.cache._redis = prev


@pytest.mark.asyncio
async def test_remember_and_get(_fake_redis):
    from bot.services.search_memory import remember_correction, get_learned_track

    track = {"video_id": "abc", "source": "yandex", "title": "My Party", "uploader": "Scriptonite"}
    assert await get_learned_track("это моя вечеринка") is None

    await remember_correction("это моя вечеринка", track)
    got = await get_learned_track("это моя вечеринка")
    assert got is not None
    assert got["video_id"] == "abc"


@pytest.mark.asyncio
async def test_normalization_matches_variants(_fake_redis):
    from bot.services.search_memory import remember_correction, get_learned_track

    track = {"video_id": "xyz", "source": "vk", "title": "T", "uploader": "A"}
    await remember_correction("Это Моя Вечеринка", track)
    # Different casing/spacing should resolve to the same learned track.
    got = await get_learned_track("  это  моя вечеринка ")
    assert got is not None
    assert got["video_id"] == "xyz"


@pytest.mark.asyncio
async def test_unrelated_query_returns_none(_fake_redis):
    from bot.services.search_memory import remember_correction, get_learned_track

    await remember_correction("track one", {"video_id": "1", "title": "x", "uploader": "y"})
    assert await get_learned_track("completely different") is None


@pytest.mark.asyncio
async def test_switch_track_resets_to_new(_fake_redis):
    from bot.services.search_memory import remember_correction, get_learned_track

    await remember_correction("my song", {"video_id": "old", "title": "x", "uploader": "y"})
    await remember_correction("my song", {"video_id": "new", "title": "x2", "uploader": "y2"})
    got = await get_learned_track("my song")
    assert got["video_id"] == "new"


@pytest.mark.asyncio
async def test_ignores_track_without_video_id(_fake_redis):
    from bot.services.search_memory import remember_correction, get_learned_track

    await remember_correction("no id song", {"title": "no id", "uploader": "y"})
    assert await get_learned_track("no id song") is None
