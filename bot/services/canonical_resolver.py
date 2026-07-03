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

from bot.config import settings
from bot.services.cache import cache
from bot.services.http_session import get_session

logger = logging.getLogger(__name__)

# Genius's Cloudflare blocks common browser UAs from datacenter IPs; an unusual
# UA passes. The API token still authorizes the request.
_GENIUS_UA = "CompuServe Classic/1.22"
_GENIUS_CACHE_PREFIX = "lyricsong:"

# Genius ranks rap battles / interviews / non-song meta pages highly for RU lyric
# fragments (e.g. "убили негра" -> a Hip-Hop.Ru battle at #0, ahead of the real
# "Запрещённые барабанщики — Убили негра" at #1). Skip these and take the first
# real song hit. Markers seen in the wild: Versus/#SLOVOSPB/Hip-Hop.Ru battles,
# вДудь interviews, "DD/MM/YY: X vs. Y" and "Round N" battle titles, Pushkin/meta.
_GENIUS_JUNK_RE = re.compile(
    r"versus|slovospb|hip-hop\.ru|stream battle|официальн\w* баттл|\bбатт?л\w*|"
    r"\bvs\.?\b|\bround\b|\bвдудь\b|\bvdud\b|евгений онегин|\bглава\b|"
    r"\d{2}[./]\d{2}[./]\d{2}|romaniz",
    re.IGNORECASE,
)

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


async def resolve_lyric_song(query: str) -> tuple[str, str] | None:
    """Resolve a lyric fragment ("words from a song") to (artist, title) via the
    Genius API. Returns None when no token is configured, on error, or no hit.
    Cached 7d. The title is the reliable signal; the artist may be a cover, so
    callers should also search the title alone and boost by title.
    """
    token = (settings.GENIUS_ACCESS_TOKEN or "").strip()
    if not token:
        return None
    q = _norm(query)
    if not q or len(q.split()) < 3:  # too short to be a distinctive lyric line
        return None

    cache_key = _GENIUS_CACHE_PREFIX + q
    try:
        cached = await cache.redis.get(cache_key)
        if cached is not None:
            if not cached:
                return None
            artist, _, title = cached.partition("\t")
            return (artist, title) if title else None
    except Exception:
        logger.debug("lyric cache read failed", exc_info=True)

    result: tuple[str, str] | None = None
    try:
        url = "https://api.genius.com/search?q=" + urllib.parse.quote(query)
        headers = {"Authorization": "Bearer " + token, "User-Agent": _GENIUS_UA}
        async with get_session().get(url, headers=headers, timeout=_TIMEOUT + 2) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                hits = data.get("response", {}).get("hits", [])
                for h in hits:
                    r = h.get("result", {})
                    artist = (r.get("primary_artist") or {}).get("name") or ""
                    title = r.get("title") or ""
                    if not (artist and title):
                        continue
                    # Skip rap-battle / interview / meta junk that Genius ranks high
                    # for RU lyric fragments — it used to pollute the resolve.
                    if _GENIUS_JUNK_RE.search(f"{artist} {title}"):
                        continue
                    # Genius appends a parenthetical transliteration/translation to
                    # BOTH fields — "Любэ (Lubeh)", "Конь (Horse)". Strip it so the
                    # artist+title matches the provider catalog (unstripped names
                    # break canonical_match_index / the direct fetch).
                    artist = re.sub(r"\s*[\(\[].*$", "", artist).strip() or artist
                    title = re.sub(r"\s*[\(\[].*$", "", title).strip() or title
                    result = (artist, title)
                    break
            else:
                logger.debug("genius search status %s", resp.status)
    except Exception:
        logger.debug("genius lyric resolve failed for %r", query, exc_info=True)

    try:
        await cache.redis.set(
            cache_key, f"{result[0]}\t{result[1]}" if result else "", ex=_CACHE_TTL
        )
    except Exception:
        logger.debug("lyric cache write failed", exc_info=True)

    return result


def title_match_index(results: list[dict], title: str) -> int | None:
    """Index of the result whose title best matches `title` (title-only, for
    lyric resolution where the artist may be a cover). Returns None if no result
    has a clearly-matching title.
    """
    tn = _norm(title)
    if not tn:
        return None
    best_i, best_score = None, 0
    for i, t in enumerate(results):
        rt = _norm(t.get("title") or "")
        if not rt:
            continue
        if rt == tn:
            score = 3
        elif tn in rt or rt in tn:
            score = 2
        else:
            continue
        if score > best_score:
            best_i, best_score = i, score
    return best_i
