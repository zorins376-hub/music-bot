"""
proxy_pool.py — Proxy rotation for yt-dlp and HTTP providers.

Parses PROXY_POOL env var (comma-separated socks5/http proxies),
round-robin selection with health tracking, auto-disable bad proxies.
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field

import aiohttp

from bot.config import settings

logger = logging.getLogger(__name__)

_HEALTH_CHECK_INTERVAL = 120  # seconds
_BAN_COOLDOWN = 60  # seconds after failure before retry
_MAX_CONSECUTIVE_FAILURES = 3


@dataclass
class _ProxyEntry:
    url: str
    successes: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    disabled_until: float = 0.0
    last_used: float = 0.0

    @property
    def is_available(self) -> bool:
        return time.monotonic() >= self.disabled_until

    def record_success(self) -> None:
        self.successes += 1
        self.consecutive_failures = 0

    def record_failure(self) -> None:
        self.failures += 1
        self.consecutive_failures += 1
        if self.consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
            self.disabled_until = time.monotonic() + _BAN_COOLDOWN
            logger.warning("Proxy %s disabled for %ds after %d failures",
                           self.url, _BAN_COOLDOWN, self.consecutive_failures)


class ProxyPool:
    def __init__(self) -> None:
        self._proxies: list[_ProxyEntry] = []
        self._index: int = 0

    def load_from_config(self) -> None:
        raw = getattr(settings, "PROXY_POOL", None) or ""
        if not raw:
            return
        urls = [u.strip() for u in raw.split(",") if u.strip()]
        self._proxies = [_ProxyEntry(url=u) for u in urls]
        logger.info("Proxy pool loaded: %d proxies", len(self._proxies))

    @property
    def size(self) -> int:
        return len(self._proxies)

    @property
    def available_count(self) -> int:
        return sum(1 for p in self._proxies if p.is_available)

    def get_next(self) -> str | None:
        """Get next available proxy URL (round-robin). Returns None if no proxies."""
        if not self._proxies:
            return None
        # Try all proxies starting from current index
        for _ in range(len(self._proxies)):
            proxy = self._proxies[self._index % len(self._proxies)]
            self._index += 1
            if proxy.is_available:
                proxy.last_used = time.monotonic()
                return proxy.url
        return None

    def record_success(self, proxy_url: str) -> None:
        for p in self._proxies:
            if p.url == proxy_url:
                p.record_success()
                return

    def record_failure(self, proxy_url: str) -> None:
        for p in self._proxies:
            if p.url == proxy_url:
                p.record_failure()
                return

    def get_status(self) -> str:
        if not self._proxies:
            return "No proxies configured."
        lines = ["<b>🔄 Proxy Pool</b>\n"]
        for p in self._proxies:
            total = p.successes + p.failures
            rate = f"{p.successes / total:.0%}" if total else "—"
            status = "🟢" if p.is_available else "🔴"
            lines.append(
                f"{status} <code>{p.url[:40]}</code>\n"
                f"   OK: {p.successes} | Fail: {p.failures} | Rate: {rate}"
            )
        lines.append(f"\nAvailable: {self.available_count}/{self.size}")
        return "\n".join(lines)

    async def health_check(self) -> None:
        """Check all proxies by making a test HTTP request."""
        for proxy in self._proxies:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        "https://www.google.com/generate_204",
                        proxy=proxy.url,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if resp.status < 400:
                            proxy.record_success()
                        else:
                            proxy.record_failure()
            except Exception:
                proxy.record_failure()


# Singleton
proxy_pool = ProxyPool()


async def start_proxy_health_scheduler() -> None:
    """Background task: periodic proxy health checks."""
    if not proxy_pool.size:
        return
    while True:
        await asyncio.sleep(_HEALTH_CHECK_INTERVAL)
        try:
            await proxy_pool.health_check()
        except Exception as e:
            logger.debug("Proxy health check error: %s", e)
