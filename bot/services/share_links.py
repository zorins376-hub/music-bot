import json
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from bot.models.base import async_session
from bot.models.share_link import ShareLink


async def create_share_link(
    owner_id: int,
    entity_type: str,
    entity_id: int,
    *,
    ttl_seconds: int | None = None,
    payload: dict | None = None,
) -> str:
    expires_at = None
    if ttl_seconds:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

    payload_raw = json.dumps(payload, ensure_ascii=False) if payload is not None else None

    async with async_session() as session:
        short_code = ""
        for _ in range(5):
            candidate = secrets.token_urlsafe(8)
            exists = await session.scalar(
                select(ShareLink.id).where(ShareLink.short_code == candidate)
            )
            if not exists:
                short_code = candidate
                break
        if not short_code:
            short_code = secrets.token_urlsafe(12)

        session.add(
            ShareLink(
                owner_id=owner_id,
                entity_type=entity_type,
                entity_id=entity_id,
                short_code=short_code,
                payload=payload_raw,
                expires_at=expires_at,
            )
        )
        await session.commit()

    return short_code


async def resolve_share_link(short_code: str) -> dict | None:
    now = datetime.now(timezone.utc)

    async with async_session() as session:
        row = await session.scalar(
            select(ShareLink).where(ShareLink.short_code == short_code)
        )
        if row is None:
            return None

        expires_at = row.expires_at
        if expires_at is not None:
            if expires_at.tzinfo is None:
                now_cmp = now.replace(tzinfo=None)
            else:
                now_cmp = now
            if expires_at <= now_cmp:
                return None

        row.clicks = int(row.clicks or 0) + 1
        await session.commit()

        payload = None
        if row.payload:
            try:
                payload = json.loads(row.payload)
            except Exception:
                payload = None

        return {
            "owner_id": row.owner_id,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "short_code": row.short_code,
            "payload": payload,
            "clicks": row.clicks,
        }
