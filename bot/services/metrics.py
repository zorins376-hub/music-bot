"""Prometheus metrics.

If prometheus_client is not installed the module provides silent no-op stubs
so the rest of the codebase can import and call metrics unconditionally.
"""
import logging

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter, Histogram, start_http_server
    _ENABLED = True
except ImportError:
    logger.debug("prometheus_client not installed — metrics disabled")
    _ENABLED = False


if _ENABLED:
    requests_total = Counter(
        "bot_requests_total",
        "Total search requests by source",
        ["source"],   # youtube / soundcloud / vk / local / cache
    )
    download_time = Histogram(
        "bot_download_seconds",
        "Time to download and send a track",
        buckets=(0.5, 1, 2, 5, 8, 15, 30, 60),
    )
    provider_errors = Counter(
        "bot_provider_errors_total",
        "Provider-level errors",
        ["provider"],
    )
    cache_hits = Counter("bot_cache_hits_total", "Telegram file_id cache hits")
    cache_misses = Counter("bot_cache_misses_total", "Telegram file_id cache misses")

else:
    class _Stub:
        def labels(self, **_): return self
        def inc(self, *_, **__): pass
        def observe(self, *_, **__): pass
        def time(self):
            import contextlib
            return contextlib.nullcontext()

    _stub = _Stub()
    requests_total = _stub
    download_time = _stub
    provider_errors = _stub
    cache_hits = _stub
    cache_misses = _stub


def start_metrics_server(port: int) -> None:
    """Start Prometheus HTTP metrics server (blocking calls in background thread)."""
    if not _ENABLED:
        logger.info("Prometheus disabled (prometheus_client not installed)")
        return
    try:
        start_http_server(port)
        logger.info("Prometheus metrics server on :%d", port)
    except Exception as e:
        logger.error("Failed to start metrics server on :%d — %s", port, e)
