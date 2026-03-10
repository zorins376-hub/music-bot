import asyncio
import json
import logging
from urllib import request as urllib_request
from datetime import datetime, timezone

from bot.config import settings
from bot.services.cache import cache

logger = logging.getLogger(__name__)


async def track_event(user_id: int, event: str, **props) -> None:
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "event": event,
        "props": props,
    }

    try:
        logger.info("analytics_event %s", json.dumps(payload, ensure_ascii=False))
    except Exception:
        pass

    try:
        await _export_event(payload)
    except Exception:
        pass

    try:
        await cache.redis.lpush("analytics:events", json.dumps(payload, ensure_ascii=False))
        await cache.redis.ltrim("analytics:events", 0, 9999)
    except Exception:
        pass


async def _export_event(payload: dict) -> bool:
    export_url = (settings.ANALYTICS_EXPORT_URL or "").strip()
    if not export_url:
        return False

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if settings.ANALYTICS_EXPORT_TOKEN:
        headers["Authorization"] = f"Bearer {settings.ANALYTICS_EXPORT_TOKEN}"

    try:
        return await asyncio.to_thread(
            _post_json,
            export_url,
            body,
            headers,
            float(settings.ANALYTICS_EXPORT_TIMEOUT_SEC or 2.0),
        )
    except Exception:
        return False


def _post_json(url: str, body: bytes, headers: dict[str, str], timeout_sec: float) -> bool:
    req = urllib_request.Request(url=url, data=body, headers=headers, method="POST")
    try:
        with urllib_request.urlopen(req, timeout=max(timeout_sec, 0.1)) as response:
            return 200 <= int(getattr(response, "status", 0)) < 300
    except Exception:
        return False
