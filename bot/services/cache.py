import json
import logging

import redis.asyncio as aioredis

from bot.config import settings

logger = logging.getLogger(__name__)


def _make_redis() -> aioredis.Redis:
    if settings.REDIS_URL.startswith("fakeredis://"):
        import fakeredis.aioredis as fakeredis
        logger.info("Using fakeredis (in-memory) — for local dev only")
        return fakeredis.FakeRedis(decode_responses=True)
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


class Cache:
    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None

    @property
    def redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = _make_redis()
        return self._redis

    # ── File ID cache ───────────────────────────────────────────────────────

    async def get_file_id(self, source_id: str, bitrate: int = 192) -> str | None:
        return await self.redis.get(f"fid:{source_id}:{bitrate}")

    async def set_file_id(
        self, source_id: str, file_id: str, bitrate: int = 192
    ) -> None:
        await self.redis.setex(
            f"fid:{source_id}:{bitrate}", settings.CACHE_FILE_ID_TTL, file_id
        )

    # ── Search sessions ─────────────────────────────────────────────────────

    async def store_search(self, session_id: str, results: list[dict]) -> None:
        await self.redis.setex(
            f"search:{session_id}",
            settings.SEARCH_SESSION_TTL,
            json.dumps(results, ensure_ascii=False),
        )

    async def get_search(self, session_id: str) -> list[dict] | None:
        data = await self.redis.get(f"search:{session_id}")
        return json.loads(data) if data else None

    # ── Global search cache (by query string) ────────────────────────────

    async def get_query_cache(self, query: str, source: str = "youtube") -> list[dict] | None:
        """Return cached search results for a query, or None."""
        key = f"qcache:{source}:{query.lower().strip()}"
        data = await self.redis.get(key)
        return json.loads(data) if data else None

    async def set_query_cache(self, query: str, results: list[dict], source: str = "youtube") -> None:
        """Cache search results for a query (120s TTL)."""
        key = f"qcache:{source}:{query.lower().strip()}"
        await self.redis.setex(key, 120, json.dumps(results, ensure_ascii=False))

    # ── Rate limiting ────────────────────────────────────────────────────────

    async def check_rate_limit(
        self, user_id: int, is_premium: bool = False
    ) -> tuple[bool, int]:
        """
        Returns (allowed, cooldown_seconds).
        cooldown_seconds > 0 → слишком быстро.
        cooldown_seconds == 0 → превышен часовой лимит.
        """
        cooldown_key = f"cd:{user_id}"
        if await self.redis.exists(cooldown_key):
            ttl = await self.redis.ttl(cooldown_key)
            return False, max(ttl, 1)

        limit_key = f"limit:{user_id}"
        count = await self.redis.incr(limit_key)
        if count == 1:
            await self.redis.expire(limit_key, 3600)

        max_limit = settings.RATE_LIMIT_PREMIUM if is_premium else settings.RATE_LIMIT_REGULAR
        if count > max_limit:
            return False, 0

        cooldown = settings.COOLDOWN_PREMIUM if is_premium else settings.COOLDOWN_REGULAR
        await self.redis.setex(cooldown_key, cooldown, "1")
        return True, 0

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()


cache = Cache()
