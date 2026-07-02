"""
provider_health.py — Track provider latency and reliability.

Records search/download timings and success rates per provider.
Provides health scores and admin-visible stats.
"""
import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_WINDOW = 100  # keep last N events per provider
_REDIS_KEY = "provider_health:v1"
_REDIS_TTL = 7 * 24 * 3600  # 7 days
_persist_task: asyncio.Task | None = None


@dataclass
class _ProviderStat:
    """Rolling window stats for a single provider."""
    latencies: list[float] = field(default_factory=list)
    successes: int = 0
    failures: int = 0
    last_error: str | None = None
    last_error_at: datetime | None = None

    @property
    def total(self) -> int:
        return self.successes + self.failures

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 1.0
        return self.successes / self.total

    @property
    def avg_latency(self) -> float:
        if not self.latencies:
            return 0.0
        return sum(self.latencies) / len(self.latencies)

    @property
    def p95_latency(self) -> float:
        if not self.latencies:
            return 0.0
        sorted_l = sorted(self.latencies)
        idx = int(len(sorted_l) * 0.95)
        return sorted_l[min(idx, len(sorted_l) - 1)]

    @property
    def health_score(self) -> float:
        """0.0 - 1.0, combining success rate and latency penalty."""
        if self.total == 0:
            return 1.0
        sr = self.success_rate
        # Penalize slow providers: > 10s avg = max penalty
        latency_penalty = min(self.avg_latency / 10.0, 1.0) * 0.3
        return max(0.0, sr - latency_penalty)

    def record_success(self, latency: float) -> None:
        self.successes += 1
        self.latencies.append(latency)
        if len(self.latencies) > _WINDOW:
            self.latencies.pop(0)

    def record_failure(self, latency: float, error: str = "") -> None:
        self.failures += 1
        self.latencies.append(latency)
        if len(self.latencies) > _WINDOW:
            self.latencies.pop(0)
        self.last_error = error[:200] if error else None
        self.last_error_at = datetime.now(timezone.utc)


# Global provider stats registry
_stats: dict[str, _ProviderStat] = defaultdict(_ProviderStat)

# Providers with health below this threshold are auto-disabled
_AUTO_DISABLE_THRESHOLD = 0.3
_disabled_providers: set[str] = set()

PROVIDERS = ("youtube", "yandex", "spotify", "vk", "soundcloud", "local")


class provider_timer:
    """Context manager to time a provider operation.

    Usage:
        with provider_timer("yandex", "search") as pt:
            results = await search_yandex(query)
        # auto-records success; on exception records failure
    """
    def __init__(self, provider: str, operation: str = "search"):
        self.provider = provider
        self.operation = operation
        self._start: float = 0

    def __enter__(self):
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = time.monotonic() - self._start
        key = f"{self.provider}:{self.operation}"
        if exc_type is None:
            _stats[key].record_success(elapsed)
        else:
            _stats[key].record_failure(elapsed, str(exc_val or ""))
        _check_auto_disable(self.provider)
        _schedule_persist()
        return False  # don't suppress exception


def record_provider_event(provider: str, operation: str, latency: float, success: bool, error: str = "") -> None:
    """Manually record a provider event."""
    key = f"{provider}:{operation}"
    if success:
        _stats[key].record_success(latency)
    else:
        _stats[key].record_failure(latency, error)
    _check_auto_disable(provider)
    _schedule_persist()


def _has_any_data() -> bool:
    return any(stat.total > 0 for stat in _stats.values())


def _serialize_stats() -> dict:
    out: dict = {}
    for key, stat in _stats.items():
        if stat.total == 0:
            continue
        out[key] = {
            "successes": stat.successes,
            "failures": stat.failures,
            "latencies": stat.latencies[-_WINDOW:],
            "last_error": stat.last_error,
            "last_error_at": stat.last_error_at.isoformat() if stat.last_error_at else None,
        }
    return out


def _deserialize_stats(data: dict) -> None:
    for key, raw in data.items():
        stat = _stats[key]
        stat.successes = int(raw.get("successes", 0))
        stat.failures = int(raw.get("failures", 0))
        stat.latencies = list(raw.get("latencies") or [])[-_WINDOW:]
        stat.last_error = raw.get("last_error")
        ts = raw.get("last_error_at")
        stat.last_error_at = datetime.fromisoformat(ts) if ts else None


def _schedule_persist() -> None:
    global _persist_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _persist_task is None or _persist_task.done():
        _persist_task = loop.create_task(_persist_stats_to_redis())


async def _persist_stats_to_redis() -> None:
    await asyncio.sleep(1)
    payload = _serialize_stats()
    if not payload:
        return
    try:
        from bot.services.cache import cache

        await cache.redis.setex(_REDIS_KEY, _REDIS_TTL, json.dumps(payload))
    except Exception:
        logger.debug("provider_health persist failed", exc_info=True)


async def ensure_stats_loaded() -> None:
    """Load persisted stats from Redis when in-memory window is empty."""
    if _has_any_data():
        return
    try:
        from bot.services.cache import cache

        raw = await cache.redis.get(_REDIS_KEY)
        if not raw:
            return
        data = json.loads(raw)
        if isinstance(data, dict):
            _deserialize_stats(data)
    except Exception:
        logger.debug("provider_health load failed", exc_info=True)


def _check_auto_disable(provider: str) -> None:
    """Disable provider if aggregate health across all operations < threshold."""
    scores = []
    for key, stat in _stats.items():
        if key.startswith(f"{provider}:") and stat.total >= 5:
            scores.append(stat.health_score)
    if not scores:
        return
    avg_health = sum(scores) / len(scores)
    if avg_health < _AUTO_DISABLE_THRESHOLD:
        if provider not in _disabled_providers:
            _disabled_providers.add(provider)
            logger.warning("Provider %s auto-disabled (health %.2f < %.2f)", provider, avg_health, _AUTO_DISABLE_THRESHOLD)
    elif provider in _disabled_providers:
        # Auto-recover when health improves
        _disabled_providers.discard(provider)
        logger.info("Provider %s auto-recovered (health %.2f)", provider, avg_health)


def is_provider_disabled(provider: str) -> bool:
    """Check if a provider is currently auto-disabled due to low health."""
    return provider in _disabled_providers


def get_disabled_providers() -> set[str]:
    """Return set of currently disabled provider names."""
    return set(_disabled_providers)


def get_provider_health(provider: str | None = None) -> dict:
    """Get health stats for one or all providers.

    Returns dict like:
        {"yandex:search": {"avg_latency": 1.2, "p95": 3.4, "success_rate": 0.95, "health": 0.88, ...}}
    """
    if provider:
        result = {}
        for key, stat in _stats.items():
            if key.startswith(provider):
                result[key] = _stat_to_dict(stat)
        return result

    return {key: _stat_to_dict(stat) for key, stat in _stats.items()}


def get_health_summary() -> str:
    """Format a human-readable health summary for admin panel."""
    if not _has_any_data():
        return (
            "<b>🩺 Здоровье провайдеров</b>\n\n"
            "Пока нет статистики — она появится после первых поисков и скачиваний.\n"
            "Если только что перезапускали бота, подождите пару запросов от пользователей."
        )

    lines = ["<b>🩺 Здоровье провайдеров</b>\n"]
    for key in sorted(_stats.keys()):
        stat = _stats[key]
        if stat.total == 0:
            continue
        emoji = "🟢" if stat.health_score > 0.7 else "🟡" if stat.health_score > 0.4 else "🔴"
        lines.append(
            f"{emoji} <b>{key}</b>: "
            f"{stat.success_rate:.0%} OK | "
            f"avg {stat.avg_latency:.1f}s | "
            f"p95 {stat.p95_latency:.1f}s | "
            f"n={stat.total}"
        )
        if stat.last_error:
            lines.append(f"   └ {stat.last_error[:80]}")

    if _disabled_providers:
        lines.append("\n<b>Отключены автоматически:</b> " + ", ".join(sorted(_disabled_providers)))

    return "\n".join(lines) if len(lines) > 1 else (
        "<b>🩺 Здоровье провайдеров</b>\n\n"
        "Пока нет статистики — она появится после первых поисков и скачиваний."
    )


def _stat_to_dict(stat: _ProviderStat) -> dict:
    return {
        "total": stat.total,
        "successes": stat.successes,
        "failures": stat.failures,
        "success_rate": round(stat.success_rate, 3),
        "avg_latency": round(stat.avg_latency, 3),
        "p95_latency": round(stat.p95_latency, 3),
        "health_score": round(stat.health_score, 3),
        "last_error": stat.last_error,
    }
