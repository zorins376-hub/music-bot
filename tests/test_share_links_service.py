from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from bot.models.share_link import ShareLink
from bot.services.share_links import create_share_link, resolve_share_link


def _patch_service_session(monkeypatch, db_session):
    class _SessionCtx:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def _factory():
        return _SessionCtx()

    monkeypatch.setattr("bot.services.share_links.async_session", _factory)


@pytest.mark.asyncio
async def test_create_and_resolve_increments_clicks(db_session, monkeypatch):
    _patch_service_session(monkeypatch, db_session)
    short_code = await create_share_link(
        owner_id=42,
        entity_type="track",
        entity_id=123,
        ttl_seconds=3600,
    )

    first = await resolve_share_link(short_code)
    second = await resolve_share_link(short_code)

    assert first is not None
    assert second is not None
    assert first["entity_type"] == "track"
    assert first["entity_id"] == 123
    assert first["clicks"] == 1
    assert second["clicks"] == 2

    row = await db_session.scalar(select(ShareLink).where(ShareLink.short_code == short_code))
    assert row is not None
    assert row.clicks == 2


@pytest.mark.asyncio
async def test_resolve_expired_share_link_returns_none(db_session, monkeypatch):
    _patch_service_session(monkeypatch, db_session)
    short_code = await create_share_link(
        owner_id=42,
        entity_type="playlist",
        entity_id=77,
        ttl_seconds=-1,
    )

    resolved = await resolve_share_link(short_code)
    assert resolved is None


@pytest.mark.asyncio
async def test_payload_roundtrip_for_mix(db_session, monkeypatch):
    _patch_service_session(monkeypatch, db_session)
    payload = {"tracks": [{"video_id": "x1", "title": "Song"}]}
    short_code = await create_share_link(
        owner_id=7,
        entity_type="mix",
        entity_id=0,
        ttl_seconds=60,
        payload=payload,
    )

    resolved = await resolve_share_link(short_code)

    assert resolved is not None
    assert resolved["entity_type"] == "mix"
    assert resolved["payload"] == payload
