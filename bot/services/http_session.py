"""Shared aiohttp.ClientSession for the bot (reuse TCP connections).

VPS-optimized: larger connection pool, keepalive tuning, better timeouts.
"""

import aiohttp
from bot.config import settings

_session: aiohttp.ClientSession | None = None


def _make_connector():
    """Create connector — SOCKS5 if PROXY_POOL is set, else optimized TCP."""
    if settings.PROXY_POOL:
        proxy_url = settings.PROXY_POOL.split(",")[0].strip()
        if proxy_url.startswith("socks"):
            try:
                from aiohttp_socks import ProxyConnector
                return ProxyConnector.from_url(
                    proxy_url,
                    limit=settings.HTTP_POOL_CONNECTIONS,
                    keepalive_timeout=settings.HTTP_POOL_KEEPALIVE,
                )
            except ImportError:
                pass
    # VPS-optimized TCP connector
    return aiohttp.TCPConnector(
        limit=settings.HTTP_POOL_CONNECTIONS,
        limit_per_host=100,  # max connections per single host
        keepalive_timeout=settings.HTTP_POOL_KEEPALIVE,
        enable_cleanup_closed=True,
        force_close=False,  # keep connections alive
    )


def _make_timeout():
    """Create client timeout from settings."""
    return aiohttp.ClientTimeout(
        total=300,  # 5 min hard cap — prevents stuck connections
        connect=settings.HTTP_CONNECT_TIMEOUT,
        sock_connect=settings.HTTP_CONNECT_TIMEOUT,
        sock_read=settings.HTTP_READ_TIMEOUT,
    )


def get_session() -> aiohttp.ClientSession:
    """Return the shared session, creating it lazily if needed."""
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            connector=_make_connector(),
            timeout=_make_timeout(),
        )
    return _session


async def close_session() -> None:
    """Close the shared session (call on shutdown)."""
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None
