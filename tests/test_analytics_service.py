import json
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_track_event_stores_payload_in_redis(cache_with_fake_redis):
    from bot.services import analytics as a

    with patch.object(a, "cache", cache_with_fake_redis), \
         patch.object(a, "_export_event", new_callable=AsyncMock, return_value=False):
        await a.track_event(42, "mix_open", count=5)

    raw = await cache_with_fake_redis.redis.lindex("analytics:events", 0)
    payload = json.loads(raw)

    assert payload["user_id"] == 42
    assert payload["event"] == "mix_open"
    assert payload["props"]["count"] == 5


@pytest.mark.asyncio
async def test_export_event_disabled_without_url():
    from bot.services import analytics as a

    with patch.object(a.settings, "ANALYTICS_EXPORT_URL", None):
        result = await a._export_event({"event": "x"})

    assert result is False


@pytest.mark.asyncio
async def test_export_event_uses_to_thread_and_headers():
    from bot.services import analytics as a

    with patch.object(a.settings, "ANALYTICS_EXPORT_URL", "https://example.test/collect"), \
         patch.object(a.settings, "ANALYTICS_EXPORT_TOKEN", "tok"), \
         patch.object(a.settings, "ANALYTICS_EXPORT_TIMEOUT_SEC", 1.0), \
         patch("bot.services.analytics.asyncio.to_thread", new_callable=AsyncMock, return_value=True) as mock_to_thread:
        result = await a._export_event({"event": "x"})

    assert result is True
    assert mock_to_thread.await_count == 1
