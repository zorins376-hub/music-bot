"""
Тесты для bot/services/cache.py
"""
import json
import pytest


@pytest.mark.asyncio
class TestCacheFileId:
    async def test_get_file_id_miss(self, cache_with_fake_redis):
        result = await cache_with_fake_redis.get_file_id("nonexistent", 192)
        assert result is None

    async def test_set_and_get_file_id(self, cache_with_fake_redis):
        await cache_with_fake_redis.set_file_id("yt_abc123", "FILEID_XYZ", 192)
        result = await cache_with_fake_redis.get_file_id("yt_abc123", 192)
        assert result == "FILEID_XYZ"

    async def test_different_bitrates_different_keys(self, cache_with_fake_redis):
        await cache_with_fake_redis.set_file_id("track1", "FID_192", 192)
        await cache_with_fake_redis.set_file_id("track1", "FID_320", 320)
        assert await cache_with_fake_redis.get_file_id("track1", 192) == "FID_192"
        assert await cache_with_fake_redis.get_file_id("track1", 320) == "FID_320"

    async def test_file_id_ttl_set(self, cache_with_fake_redis):
        await cache_with_fake_redis.set_file_id("track_ttl", "FID", 128)
        ttl = await cache_with_fake_redis.redis.ttl("fid:track_ttl:128")
        assert ttl > 0


@pytest.mark.asyncio
class TestCacheSearch:
    async def test_store_and_get_search(self, cache_with_fake_redis):
        results = [{"video_id": "abc", "title": "Song", "uploader": "Artist"}]
        await cache_with_fake_redis.store_search("sess123", results)
        retrieved = await cache_with_fake_redis.get_search("sess123")
        assert retrieved == results

    async def test_get_search_missing(self, cache_with_fake_redis):
        assert await cache_with_fake_redis.get_search("no_such_session") is None

    async def test_search_unicode(self, cache_with_fake_redis):
        results = [{"title": "Трек на русском 🎵", "uploader": "Исполнитель"}]
        await cache_with_fake_redis.store_search("rus_sess", results)
        retrieved = await cache_with_fake_redis.get_search("rus_sess")
        assert retrieved[0]["title"] == "Трек на русском 🎵"


@pytest.mark.asyncio
class TestCacheQueryCache:
    async def test_query_cache_miss(self, cache_with_fake_redis):
        result = await cache_with_fake_redis.get_query_cache("unknown song", "youtube")
        assert result is None

    async def test_set_and_get_query_cache(self, cache_with_fake_redis):
        data = [{"video_id": "yt1", "title": "Test Track"}]
        await cache_with_fake_redis.set_query_cache("test song", data, "youtube")
        result = await cache_with_fake_redis.get_query_cache("test song", "youtube")
        assert result == data

    async def test_query_cache_case_insensitive(self, cache_with_fake_redis):
        data = [{"video_id": "yt2", "title": "Bones"}]
        await cache_with_fake_redis.set_query_cache("Bones", data, "youtube")
        result = await cache_with_fake_redis.get_query_cache("bones", "youtube")
        assert result == data

    async def test_different_sources_separate_keys(self, cache_with_fake_redis):
        yt_data = [{"video_id": "yt3", "source": "youtube"}]
        sc_data = [{"video_id": "sc1", "source": "soundcloud"}]
        await cache_with_fake_redis.set_query_cache("artist", yt_data, "youtube")
        await cache_with_fake_redis.set_query_cache("artist", sc_data, "soundcloud")
        assert await cache_with_fake_redis.get_query_cache("artist", "youtube") == yt_data
        assert await cache_with_fake_redis.get_query_cache("artist", "soundcloud") == sc_data


@pytest.mark.asyncio
class TestCacheRateLimit:
    async def test_first_request_allowed(self, cache_with_fake_redis):
        allowed, cooldown = await cache_with_fake_redis.check_rate_limit(999, is_premium=False)
        assert allowed is True
        assert cooldown == 0

    async def test_cooldown_blocks_second_request(self, cache_with_fake_redis):
        user_id = 888
        await cache_with_fake_redis.check_rate_limit(user_id, is_premium=False)
        allowed, cooldown = await cache_with_fake_redis.check_rate_limit(user_id, is_premium=False)
        assert allowed is False
        assert cooldown > 0

    async def test_premium_shorter_cooldown_key(self, cache_with_fake_redis):
        """Premium пользователи тоже проходят, но cooldown меньше."""
        user_id = 777
        allowed, _ = await cache_with_fake_redis.check_rate_limit(user_id, is_premium=True)
        assert allowed is True
