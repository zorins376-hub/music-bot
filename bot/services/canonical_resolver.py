"""Canonical query resolver.

Users in chats often type just a song title (no artist) or a misspelled query.
Free music catalogs (iTunes Search, Deezer) are good at mapping such a query to
a canonical "Artist - Title" — but their per-source top hit is noisy (covers,
remixes, obscure artists). So we only trust a canonical when iTunes AND Deezer
INDEPENDENTLY agree on the same artist+title. That agreement is a strong, safe
signal (verified: "мокрые кросы" [typo] -> "Тима Белорусских - Мокрые кроссы",
"душный" -> "Seryabkina - Душный"); ambiguous queries with no cross-source
agreement (e.g. "розовое вино", where catalogs disagree) return None and the
caller leaves search untouched — so this can only help, never regress.

Pure/soft: returns a query STRING (or None); any error/timeout -> None. Lyric
fragments are out of scope (need a keyed web/lyrics API).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.parse

from bot.services.cache import cache
from bot.services.http_session import get_session

logger = logging.getLogger(__name__)

_CACHE_TTL = 7 * 24 * 3600  # 7 days
_CACHE_PREFIX = "canon:"
_TIMEOUT = 4
_UA = "Mozilla/5.0 (compatible; BlackRoomBot/1.0)"
_BRACKETS = re.compile(r"[\(\[\{].*?[\)\]\}]")


def _norm(s: str) -> str:
    s = (s or "").lower().replace("ё", "е")
    s = _BRACKETS.sub("", s)  # drop "(remix)", "[prod. ...]" etc.
    return " ".join(re.sub(r"[^\w\s]", " ", s).split())


def _artist_match(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    # first significant token equal (handles "5sta family & dj x" vs "5sta family")
    return a.split()[0] == b.split()[0]


async def _itunes(query: str) -> list[tuple[str, str]]:
    url = "https://itunes.apple.com/search?media=music&limit=3&term=" + urllib.parse.quote(query)
    async with get_session().get(url, headers={"User-Agent": _UA}, timeout=_TIMEOUT) as resp:
        if resp.status != 200:
            return []
        data = json.loads(await resp.text())  # iTunes serves JSON as text/javascript
    return [(r.get("artistName") or "", r.get("trackName") or "") for r in data.get("results", []) if r.get("artistName") and r.get("trackName")]


async def _deezer(query: str) -> list[tuple[str, str]]:
    url = "https://api.deezer.com/search?limit=3&q=" + urllib.parse.quote(query)
    async with get_session().get(url, headers={"User-Agent": _UA}, timeout=_TIMEOUT) as resp:
        if resp.status != 200:
            return []
        data = await resp.json(content_type=None)
    return [((r.get("artist") or {}).get("name") or "", r.get("title") or "") for r in data.get("data", []) if (r.get("artist") or {}).get("name") and r.get("title")]


def _confident(itunes: list[tuple[str, str]], deezer: list[tuple[str, str]]) -> str | None:
    """Return 'Artist Title' only if iTunes and Deezer agree on artist+title."""
    for ia, it in itunes:
        for da, dt in deezer:
            if _norm(it) == _norm(dt) and _artist_match(ia, da):
                # Prefer the Cyrillic spelling if one side is transliterated latin.
                artist = da if re.search(r"[а-я]", da.lower()) else ia
                title = dt if re.search(r"[а-я]", dt.lower()) else it
                return f"{artist} {title}".strip()
    return None


async def resolve_canonical(query: str) -> str | None:
    """Confident canonical 'Artist Title' for a raw query, or None. Cached 7d."""
    q = _norm(query)
    if not q or len(q) < 2 or len(q.split()) > 8:
        return None

    cache_key = _CACHE_PREFIX + q
    try:
        cached = await cache.redis.get(cache_key)
        if cached is not None:
            return cached or None  # "" sentinel = resolved-but-no-canonical
    except Exception:
        logger.debug("canon cache read failed", exc_info=True)

    itunes: list[tuple[str, str]] = []
    deezer: list[tuple[str, str]] = []
    try:
        res = await asyncio.gather(_itunes(query), _deezer(query), return_exceptions=True)
        itunes = res[0] if isinstance(res[0], list) else []
        deezer = res[1] if isinstance(res[1], list) else []
    except Exception:
        logger.debug("canon resolve failed for %r", query, exc_info=True)

    canon = _confident(itunes, deezer)

    try:
        await cache.redis.set(cache_key, canon or "", ex=_CACHE_TTL)
    except Exception:
        logger.debug("canon cache write failed", exc_info=True)

    return canon


def canonical_match_index(results: list[dict], canon: str) -> int | None:
    """Index of the result that best matches a confident canonical 'Artist Title'.

    Requires the title to match and the artist to match — so we only ever promote
    a result we are confident is the intended track. Returns None if no result
    matches (then the caller leaves ranking untouched).
    """
    cn = _norm(canon)
    best_i, best_score = None, 0
    for i, t in enumerate(results):
        artist = _norm(t.get("uploader") or "")
        title = _norm(t.get("title") or "")
        if not title:
            continue
        # canon is "artist title"; require the title to be present and the artist to overlap
        if title and title in cn:
            score = len(title)
            if artist and (artist in cn or (artist.split()[0] in cn.split())):
                score += 100  # artist+title match — strong
            if score > best_score:
                best_i, best_score = i, score
    # only promote on a strong (artist+title) match
    return best_i if best_score >= 100 else None
