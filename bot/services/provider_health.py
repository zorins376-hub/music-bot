"""
provider_health.py — Track provider latency and reliability.

Records search/download timings and success rates per provider.
Provides health scores and admin-visible stats.
"""
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_WINDOW = 100  # keep last N events per provider


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
        return False  # don't suppress exception


def record_provider_event(provider: str, operation: str, latency: float, success: bool, error: str = "") -> None:
    """Manually record a provider event."""
    key = f"{provider}:{operation}"
    if success:
        _stats[key].record_success(latency)
    else:
        _stats[key].record_failure(latency, error)


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
    if not _stats:
        return "No provider data yet."

    lines = ["<b>Provider Health</b>\n"]
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
            lines.append(f"   └ last err: {stat.last_error[:60]}")

    return "\n".join(lines) if len(lines) > 1 else "No provider data yet."


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
