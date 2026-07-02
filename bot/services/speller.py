"""Yandex Speller integration for typo correction in search queries.

Free API: https://yandex.ru/dev/speller/
No auth needed, no rate limits for reasonable usage.
"""

import logging
from urllib.parse import quote

try:
    import aiohttp
except ImportError:
    aiohttp = None  # type: ignore

logger = logging.getLogger(__name__)

_SPELLER_URL = "https://speller.yandex.net/services/spellservice.json/checkText"
_TIMEOUT = 2.0  # seconds — speller should be fast, don't block search


async def correct_query(query: str) -> str | None:
    """Return corrected query if Yandex Speller suggests fixes, else None.

    Returns None if:
    - No corrections needed
    - API is unavailable
    - Timeout exceeded
    """
    if aiohttp is None:
        return None
    if not query or len(query) > 200:
        return None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                _SPELLER_URL,
                params={"text": query, "lang": "ru,en"},
                timeout=aiohttp.ClientTimeout(total=_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

        if not data:
            return None

        # Apply corrections right-to-left to preserve positions
        corrected = query
        for change in reversed(data):
            if not change.get("s"):
                continue
            pos = change.get("pos", 0)
            length = change.get("len", 0)
            replacement = change["s"][0]  # First suggestion
            corrected = corrected[:pos] + replacement + corrected[pos + length:]

        # Only return if actually different
        if corrected.lower().strip() != query.lower().strip():
            logger.info("speller: %r -> %r", query, corrected)
            return corrected
        return None

    except Exception as e:
        logger.debug("speller failed: %s", e)
        return None
