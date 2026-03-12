"""Shared aiohttp.ClientSession for the bot (reuse TCP connections)."""

import aiohttp
from bot.config import settings

_session: aiohttp.ClientSession | None = None


def _make_connector():
    """Create connector — SOCKS5 if PROXY_POOL is set, else default TCP."""
    if settings.PROXY_POOL:
        proxy_url = settings.PROXY_POOL.split(",")[0].strip()
        if proxy_url.startswith("socks"):
            try:
                from aiohttp_socks import ProxyConnector
                return ProxyConnector.from_url(proxy_url)
            except ImportError:
                pass
    return aiohttp.TCPConnector()


def get_session() -> aiohttp.ClientSession:
    """Return the shared session, creating it lazily if needed."""
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(connector=_make_connector())
    return _session


async def close_session() -> None:
    """Close the shared session (call on shutdown)."""
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None
