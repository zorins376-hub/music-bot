from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_get_or_build_daily_mix_returns_cache_first():
    from bot.services import daily_mix as dm

    with patch.object(dm, "cache") as mock_cache, \
         patch.object(dm, "_load_daily_mix_from_db", new_callable=AsyncMock) as mock_load_db, \
         patch.object(dm, "_build_daily_mix_tracks", new_callable=AsyncMock) as mock_build, \
         patch.object(dm, "_save_daily_mix_to_db", new_callable=AsyncMock) as mock_save:
        mock_cache.redis.get = AsyncMock(return_value='[{"video_id":"v1"}]')
        mock_cache.redis.setex = AsyncMock()

        result = await dm.get_or_build_daily_mix(user_id=1, limit=25)

        assert result == [{"video_id": "v1"}]
        mock_load_db.assert_not_called()
        mock_build.assert_not_called()
        mock_save.assert_not_called()


@pytest.mark.asyncio
async def test_get_or_build_daily_mix_uses_db_when_cache_miss():
    from bot.services import daily_mix as dm

    db_tracks = [{"video_id": "db1"}]

    with patch.object(dm, "cache") as mock_cache, \
         patch.object(dm, "_load_daily_mix_from_db", new_callable=AsyncMock, return_value=db_tracks) as mock_load_db, \
         patch.object(dm, "_build_daily_mix_tracks", new_callable=AsyncMock) as mock_build, \
         patch.object(dm, "_save_daily_mix_to_db", new_callable=AsyncMock) as mock_save:
        mock_cache.redis.get = AsyncMock(return_value=None)
        mock_cache.redis.setex = AsyncMock()

        result = await dm.get_or_build_daily_mix(user_id=1, limit=25)

        assert result == db_tracks
        mock_load_db.assert_awaited_once()
        mock_build.assert_not_called()
        mock_save.assert_not_called()


@pytest.mark.asyncio
async def test_get_or_build_daily_mix_builds_and_persists_when_no_cache_or_db():
    from bot.services import daily_mix as dm

    built = [
        {"video_id": "b1", "title": "Song", "uploader": "Artist", "duration": 10, "duration_fmt": "0:10", "source": "youtube"}
    ]

    with patch.object(dm, "cache") as mock_cache, \
         patch.object(dm, "_load_daily_mix_from_db", new_callable=AsyncMock, return_value=[]) as mock_load_db, \
         patch.object(dm, "_build_daily_mix_tracks", new_callable=AsyncMock, return_value=[object()]) as mock_build, \
         patch.object(dm, "_save_daily_mix_to_db", new_callable=AsyncMock) as mock_save, \
         patch.object(dm, "_track_to_result", return_value=built[0]):
        mock_cache.redis.get = AsyncMock(return_value=None)
        mock_cache.redis.setex = AsyncMock()

        result = await dm.get_or_build_daily_mix(user_id=1, limit=25)

        assert result == built
        mock_load_db.assert_awaited_once()
        mock_build.assert_awaited_once()
        mock_save.assert_awaited_once()
