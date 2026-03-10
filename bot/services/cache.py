import json
import logging
import time
import asyncio
from collections import defaultdict
from collections import deque

import redis.asyncio as aioredis

from bot.config import settings

logger = logging.getLogger(__name__)

# ── In-memory fallback rate limiter (used when Redis is unavailable) ─────
_mem_counts: dict[int, list[float]] = defaultdict(list)
_mem_cooldowns: dict[int, float] = {}
_redis_down_logged = False


def _make_redis() -> aioredis.Redis:
    if settings.REDIS_URL.startswith("fakeredis://"):
        import fakeredis.aioredis as fakeredis
        logger.info("Using fakeredis (in-memory) — for local dev only")
        return fakeredis.FakeRedis(decode_responses=True)
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


class RateLimitedRedis:
    """Thin Redis proxy with optional per-process request throttling."""

    def __init__(self, client: aioredis.Redis, max_ops_per_sec: int = 0, burst: int = 50) -> None:
        self._client = client
        self._max_ops_per_sec = max(0, int(max_ops_per_sec or 0))
        self._burst = max(1, int(burst or 1))
        self._recent_ops: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def _throttle(self) -> None:
        if self._max_ops_per_sec <= 0:
            return

        limit = min(self._burst, self._max_ops_per_sec)
        while True:
            async with self._lock:
                now = time.monotonic()
                cutoff = now - 1.0
                while self._recent_ops and self._recent_ops[0] <= cutoff:
                    self._recent_ops.popleft()

                if len(self._recent_ops) < limit:
                    self._recent_ops.append(now)
                    return

                wait_for = max(0.0, self._recent_ops[0] + 1.0 - now)

            if wait_for > 0:
                await asyncio.sleep(wait_for)
            else:
                await asyncio.sleep(0)

    async def get(self, *args, **kwargs):
        await self._throttle()
        return await self._client.get(*args, **kwargs)

    async def set(self, *args, **kwargs):
        await self._throttle()
        return await self._client.set(*args, **kwargs)

    async def setex(self, *args, **kwargs):
        await self._throttle()
        return await self._client.setex(*args, **kwargs)

    async def exists(self, *args, **kwargs):
        await self._throttle()
        return await self._client.exists(*args, **kwargs)

    async def ttl(self, *args, **kwargs):
        await self._throttle()
        return await self._client.ttl(*args, **kwargs)

    async def incr(self, *args, **kwargs):
        await self._throttle()
        return await self._client.incr(*args, **kwargs)

    async def expire(self, *args, **kwargs):
        await self._throttle()
        return await self._client.expire(*args, **kwargs)

    async def publish(self, *args, **kwargs):
        await self._throttle()
        return await self._client.publish(*args, **kwargs)

    async def lrange(self, *args, **kwargs):
        await self._throttle()
        return await self._client.lrange(*args, **kwargs)

    async def delete(self, *args, **kwargs):
        await self._throttle()
        return await self._client.delete(*args, **kwargs)

    async def rpush(self, *args, **kwargs):
        await self._throttle()
        return await self._client.rpush(*args, **kwargs)

    async def sadd(self, *args, **kwargs):
        await self._throttle()
        return await self._client.sadd(*args, **kwargs)

    async def smembers(self, *args, **kwargs):
        await self._throttle()
        return await self._client.smembers(*args, **kwargs)

    async def aclose(self) -> None:
        await self._client.aclose()

    def __getattr__(self, item):
        return getattr(self._client, item)


class Cache:
    def __init__(self) -> None:
        self._redis: aioredis.Redis | RateLimitedRedis | None = None
        self._metrics: dict[str, float] = {
            "gets": 0,
            "hits": 0,
            "latency_ms_total": 0.0,
            "latency_samples": 0,
        }

    @property
    def redis(self) -> aioredis.Redis | RateLimitedRedis:
        if self._redis is None:
            self._redis = RateLimitedRedis(
                _make_redis(),
                max_ops_per_sec=settings.REDIS_MAX_OPS_PER_SEC,
                burst=settings.REDIS_BURST,
            )
        return self._redis

    # ── File ID cache ───────────────────────────────────────────────────────

    async def get_file_id(self, source_id: str, bitrate: int = 192) -> str | None:
        start = time.perf_counter()
        try:
            value = await self.redis.get(f"fid:{source_id}:{bitrate}")
            self._record_get_metric(hit=bool(value), started_at=start)
            return value
        except Exception:
            self._record_get_metric(hit=False, started_at=start)
            return None

    async def set_file_id(
        self, source_id: str, file_id: str, bitrate: int = 192
    ) -> None:
        try:
            await self.redis.setex(
                f"fid:{source_id}:{bitrate}", settings.CACHE_FILE_ID_TTL, file_id
            )
        except Exception:
            pass

    # ── Search sessions ─────────────────────────────────────────────────────

    async def store_search(self, session_id: str, results: list[dict]) -> None:
        try:
            await self.redis.setex(
                f"search:{session_id}",
                settings.SEARCH_SESSION_TTL,
                json.dumps(results, ensure_ascii=False),
            )
        except Exception:
            pass

    async def get_search(self, session_id: str) -> list[dict] | None:
        start = time.perf_counter()
        try:
            data = await self.redis.get(f"search:{session_id}")
            self._record_get_metric(hit=bool(data), started_at=start)
            return json.loads(data) if data else None
        except Exception:
            self._record_get_metric(hit=False, started_at=start)
            return None

    # ── Global search cache (by query string) ────────────────────────────

    async def get_query_cache(self, query: str, source: str = "youtube") -> list[dict] | None:
        """Return cached search results for a query, or None."""
        start = time.perf_counter()
        try:
            key = f"qcache:{source}:{query.lower().strip()}"
            data = await self.redis.get(key)
            self._record_get_metric(hit=bool(data), started_at=start)
            return json.loads(data) if data else None
        except Exception:
            self._record_get_metric(hit=False, started_at=start)
            return None

    def _record_get_metric(self, hit: bool, started_at: float) -> None:
        latency_ms = (time.perf_counter() - started_at) * 1000.0
        self._metrics["gets"] += 1
        self._metrics["latency_samples"] += 1
        self._metrics["latency_ms_total"] += latency_ms
        if hit:
            self._metrics["hits"] += 1

    def get_runtime_metrics(self) -> dict[str, float]:
        gets = int(self._metrics.get("gets", 0))
        hits = int(self._metrics.get("hits", 0))
        latency_samples = int(self._metrics.get("latency_samples", 0))
        latency_total = float(self._metrics.get("latency_ms_total", 0.0))
        hit_rate = (hits * 100.0 / gets) if gets else 0.0
        avg_latency_ms = (latency_total / latency_samples) if latency_samples else 0.0
        return {
            "gets": gets,
            "hits": hits,
            "hit_rate": hit_rate,
            "avg_latency_ms": avg_latency_ms,
        }

    async def set_query_cache(self, query: str, results: list[dict], source: str = "youtube") -> None:
        """Cache search results for a query (120s TTL)."""
        try:
            key = f"qcache:{source}:{query.lower().strip()}"
            await self.redis.setex(key, 120, json.dumps(results, ensure_ascii=False))
        except Exception:
            pass

    # ── Rate limiting ────────────────────────────────────────────────────────

    async def check_rate_limit(
        self, user_id: int, is_premium: bool = False
    ) -> tuple[bool, int]:
        """
        Returns (allowed, cooldown_seconds).
        cooldown_seconds > 0 → слишком быстро.
        cooldown_seconds == 0 → превышен часовой лимит.
        Redis unavailable → in-memory fallback (stricter limits).
        """
        try:
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
        except Exception:
            # Redis unavailable → in-memory fallback with stricter limits
            return self._check_rate_limit_memory(user_id, is_premium)

    @staticmethod
    def _check_rate_limit_memory(
        user_id: int, is_premium: bool
    ) -> tuple[bool, int]:
        """In-memory rate limiter used when Redis is down."""
        global _redis_down_logged
        if not _redis_down_logged:
            logger.warning("Redis unavailable — using in-memory rate limiter")
            _redis_down_logged = True

        now = time.monotonic()

        # Cooldown check
        cd_end = _mem_cooldowns.get(user_id, 0)
        if now < cd_end:
            return False, max(1, int(cd_end - now))

        # Hourly limit (stricter: 8 for regular, still high for premium)
        max_limit = settings.RATE_LIMIT_PREMIUM if is_premium else max(settings.RATE_LIMIT_REGULAR - 2, 5)
        timestamps = _mem_counts[user_id]
        # Prune entries older than 1 hour
        cutoff = now - 3600
        _mem_counts[user_id] = [ts for ts in timestamps if ts > cutoff]
        timestamps = _mem_counts[user_id]

        if len(timestamps) >= max_limit:
            return False, 0

        timestamps.append(now)
        cooldown = settings.COOLDOWN_PREMIUM if is_premium else settings.COOLDOWN_REGULAR
        _mem_cooldowns[user_id] = now + cooldown
        return True, 0

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()


cache = Cache()
