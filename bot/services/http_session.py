"""Shared aiohttp.ClientSession for the bot (reuse TCP connections)."""

import aiohttp

_session: aiohttp.ClientSession | None = None


def get_session() -> aiohttp.ClientSession:
    """Return the shared session, creating it lazily if needed."""
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session


async def close_session() -> None:
    """Close the shared session (call on shutdown)."""
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None
