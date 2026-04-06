"""Search engine: query normalization, deduplication, transliteration.

TASK-001: Fuzzy search + dedup + multi-language support (TASK-023).
"""

import asyncio
import logging
import re
import unicodedata

try:
    from rapidfuzz import fuzz as _rf_fuzz
except Exception:
    _rf_fuzz = None

# ── Transliteration tables ────────────────────────────────────────────────

_CYR_TO_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

_LAT_TO_CYR = {
    "a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г",
    "h": "х", "i": "и", "j": "дж", "k": "к", "l": "л", "m": "м", "n": "н",
    "o": "о", "p": "п", "q": "к", "r": "р", "s": "с", "t": "т", "u": "у",
    "v": "в", "w": "в", "x": "кс", "y": "й", "z": "з",
}

# Multi-char Latin → Cyrillic mappings (applied first, order matters)
_LAT_DIGRAPHS_TO_CYR = [
    ("sh", "ш"), ("ch", "ч"), ("zh", "ж"), ("th", "т"),
    ("ph", "ф"), ("kh", "х"), ("ts", "ц"), ("ya", "я"),
    ("yu", "ю"), ("yo", "ё"),
]


def transliterate_cyr_to_lat(text: str) -> str:
    """Convert Cyrillic text to Latin transliteration."""
    result = []
    for ch in text.lower():
        result.append(_CYR_TO_LAT.get(ch, ch))
    return "".join(result)


def transliterate_lat_to_cyr(text: str) -> str:
    """Convert Latin text to Cyrillic transliteration."""
    text = text.lower()
    for lat, cyr in _LAT_DIGRAPHS_TO_CYR:
        text = text.replace(lat, cyr)
    result = []
    for ch in text:
        result.append(_LAT_TO_CYR.get(ch, ch))
    return "".join(result)


# ── Query normalization ───────────────────────────────────────────────────

_JUNK_RE = re.compile(r"[?!.,;:'\"\(\)\[\]{}]")
_MULTI_SPACE = re.compile(r"\s{2,}")


def normalize_query(query: str) -> str:
    """Normalize a search query: strip junk, normalize whitespace, lowercase."""
    q = query.strip().lower()
    q = _JUNK_RE.sub(" ", q)
    q = _MULTI_SPACE.sub(" ", q)
    return q.strip()


def detect_script(text: str) -> str:
    """Detect dominant script: 'cyrillic', 'latin', or 'mixed'."""
    cyr = 0
    lat = 0
    for ch in text:
        if ch.isalpha():
            try:
                name = unicodedata.name(ch, "")
            except ValueError:
                continue
            if "CYRILLIC" in name:
                cyr += 1
            elif "LATIN" in name:
                lat += 1
    if cyr and not lat:
        return "cyrillic"
    if lat and not cyr:
        return "latin"
    return "mixed"


# ── Deduplication ─────────────────────────────────────────────────────────

_FEAT_RE = re.compile(r"\s*[\(\[]?\s*(?:feat\.?|ft\.?)\s*[^)\]]*[\)\]]?", re.IGNORECASE)
# Source quality ranking (higher = better)
_SOURCE_RANK = {"yandex": 5, "spotify": 4, "deezer": 4, "apple": 3, "vk": 3, "soundcloud": 2, "youtube": 1, "channel": 6}
# Language-aware: Russian queries prioritize Yandex/VK; English → Spotify/Deezer/YouTube
_SOURCE_RANK_CYR = {"yandex": 6, "vk": 5, "deezer": 4, "spotify": 3, "apple": 3, "channel": 6, "soundcloud": 2, "youtube": 1}
_SOURCE_RANK_LAT = {"spotify": 6, "deezer": 5, "apple": 5, "youtube": 4, "soundcloud": 3, "yandex": 3, "vk": 2, "channel": 6}


def _normalize_for_dedup(artist: str, title: str) -> str:
    """Normalize artist+title for duplicate detection."""
    s = f"{artist} {title}".lower().strip()
    s = _FEAT_RE.sub("", s)
    s = _JUNK_RE.sub("", s)
    s = _MULTI_SPACE.sub(" ", s)
    return s.strip()


def _jaccard_similarity(a: str, b: str) -> float:
    """Word-level Jaccard similarity between two strings."""
    set_a = set(a.split())
    set_b = set(b.split())
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def _relevance_score(query_norm: str, artist: str, title: str, position: int = 0) -> float:
    """Score how relevant a track is to the search query (0.0 - 2.5+).

    Multi-signal scoring:
    1. Word overlap (exact + substring)
    2. Artist match bonus (query matches artist name specifically)
    3. Position bonus (match at start of title/artist)
    4. RapidFuzz token_sort_ratio (catches typos & word reorder)
    5. Title brevity bonus (shorter = less junk = more precise)
    6. Provider position bonus (earlier results from each provider are better)
    """
    query_words = query_norm.split()
    if not query_words:
        return 0.0
    query_set = set(query_words)

    artist_lower = artist.lower().strip()
    title_lower = title.lower().strip()
    track_text = f"{artist_lower} {title_lower}"
    track_words = set(track_text.split())

    # 1. Word overlap (0.0 - 1.0)
    exact = len(query_set & track_words)
    substring = 0
    for qw in query_set - track_words:
        if qw in track_text:
            substring += 0.5
    word_score = (exact + substring) / len(query_words)

    # 2. Artist match bonus (0.0 - 0.4)
    # If the query contains the artist name or vice versa — boost
    artist_bonus = 0.0
    artist_words = set(artist_lower.split())
    if artist_words and query_set:
        artist_overlap = len(query_set & artist_words) / max(len(artist_words), len(query_set))
        if artist_overlap >= 0.4:
            artist_bonus = 0.4 * artist_overlap

    # 3. Position bonus (0.0 - 0.15): query found at start of artist or title
    position_bonus = 0.0
    if artist_lower.startswith(query_norm) or title_lower.startswith(query_norm):
        position_bonus = 0.15
    elif track_text.startswith(query_norm):
        position_bonus = 0.1

    # 4. RapidFuzz bonus (0.0 - 0.5): catches typos and word reorder
    fuzz_bonus = 0.0
    if _rf_fuzz is not None:
        ratio = float(_rf_fuzz.token_sort_ratio(query_norm, track_text)) / 100.0
        fuzz_bonus = ratio * 0.5

    # 5. Title brevity bonus (0.0 - 0.1): shorter titles = more precise match
    total_words = len(track_text.split())
    if total_words > 0:
        brevity = max(0.0, 1.0 - (total_words - len(query_words)) / 10.0)
        brevity_bonus = brevity * 0.1
    else:
        brevity_bonus = 0.0

    # 6. Provider position bonus (0.0 - 0.3): first results from provider are more relevant
    provider_bonus = max(0.0, 0.3 - position * 0.03)

    return word_score + artist_bonus + position_bonus + fuzz_bonus + brevity_bonus + provider_bonus


def deduplicate_results(results: list[dict], threshold: float = 0.7, lang_hint: str = "mixed", query: str = "") -> list[dict]:
    """Remove duplicate tracks, keeping the one from the best source.
    Then re-rank by relevance to the original query."""
    if not results:
        return []

    # Pick ranking table based on query language
    if lang_hint == "cyrillic":
        rank = _SOURCE_RANK_CYR
    elif lang_hint == "latin":
        rank = _SOURCE_RANK_LAT
    else:
        rank = _SOURCE_RANK

    # Sort by source quality (best first) for dedup — keep best source version
    ranked = sorted(results, key=lambda r: rank.get(r.get("source", ""), 0), reverse=True)

    kept: list[dict] = []
    kept_keys: list[str] = []

    for track in ranked:
        key = _normalize_for_dedup(
            track.get("uploader", ""),
            track.get("title", ""),
        )
        is_dup = False
        for existing_key in kept_keys:
            # Use rapidfuzz token_sort_ratio if available (better than Jaccard for music titles)
            if _rf_fuzz is not None:
                sim = float(_rf_fuzz.token_sort_ratio(key, existing_key)) / 100.0
            else:
                sim = _jaccard_similarity(key, existing_key)
            if sim >= threshold:
                is_dup = True
                break
        if not is_dup:
            kept.append(track)
            kept_keys.append(key)

    # Re-rank by relevance to original query
    if query:
        query_norm = normalize_query(query)
        kept.sort(
            key=lambda t: (
                _relevance_score(
                    query_norm,
                    t.get("uploader", ""),
                    t.get("title", ""),
                    position=t.get("_provider_pos", 5),
                ),
                rank.get(t.get("source", ""), 0),
            ),
            reverse=True,
        )

    return kept


# ── "Did you mean?" suggestions ──────────────────────────────────────────

def suggest_query(query: str, corpus: list[str], max_suggestions: int = 1) -> list[str]:
    """Find closest matches from corpus for a failed query.

    Uses word-level Jaccard + character bigram similarity.
    Returns up to *max_suggestions* candidates.
    """
    norm = normalize_query(query)
    if not norm:
        return []

    def _bigram_sim(a: str, b: str) -> float:
        """Character bigram similarity (Dice coefficient)."""
        if len(a) < 2 or len(b) < 2:
            return 1.0 if a == b else 0.0
        bg_a = {a[i:i + 2] for i in range(len(a) - 1)}
        bg_b = {b[i:i + 2] for i in range(len(b) - 1)}
        if not bg_a or not bg_b:
            return 0.0
        return 2 * len(bg_a & bg_b) / (len(bg_a) + len(bg_b))

    def _rapidfuzz_sim(a: str, b: str) -> float:
        if _rf_fuzz is None:
            return 0.0
        return float(_rf_fuzz.token_set_ratio(a, b)) / 100.0

    scored: list[tuple[float, str]] = []
    for entry in corpus:
        entry_norm = normalize_query(entry)
        if not entry_norm:
            continue
        jac = _jaccard_similarity(norm, entry_norm)
        big = _bigram_sim(norm, entry_norm)
        rf = _rapidfuzz_sim(norm, entry_norm)
        if _rf_fuzz is not None:
            score = jac * 0.25 + big * 0.35 + rf * 0.40
        else:
            score = jac * 0.4 + big * 0.6
        if score > 0.3:
            scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [s[1] for s in scored[:max_suggestions]]


# ── Main search function ─────────────────────────────────────────────────

logger = logging.getLogger(__name__)


async def perform_search(query: str, limit: int = 10) -> list[dict]:
    """Search across all providers, deduplicate and return merged results."""
    from bot.services.downloader import search_tracks as yt_search

    tasks: list[asyncio.Task] = [yt_search(query, max_results=limit)]

    # Add all available providers (same as bot handler)
    try:
        from bot.services.yandex_provider import search_yandex
        tasks.append(search_yandex(query, limit=limit))
    except Exception:
        logger.debug("yandex provider import failed", exc_info=True)

    try:
        from bot.services.spotify_provider import search_spotify
        tasks.append(search_spotify(query, limit=limit))
    except Exception:
        logger.debug("spotify provider import failed", exc_info=True)

    try:
        from bot.services.vk_provider import search_vk
        tasks.append(search_vk(query, limit=limit))
    except Exception:
        logger.debug("vk provider import failed", exc_info=True)

    try:
        from bot.services.deezer_provider import search_deezer
        tasks.append(search_deezer(query, limit=limit))
    except Exception:
        logger.debug("deezer provider import failed", exc_info=True)

    try:
        from bot.services.apple_provider import search_apple
        tasks.append(search_apple(query, limit=limit))
    except Exception:
        logger.debug("apple provider import failed", exc_info=True)

    results_lists = await asyncio.gather(*tasks, return_exceptions=True)

    merged: list[dict] = []
    for result in results_lists:
        if isinstance(result, list):
            for i, track in enumerate(result):
                track["_provider_pos"] = i
            merged.extend(result)

    if not merged:
        logger.warning("No search results for query: %s", query)
        return []

    lang_hint = detect_script(query)
    deduped = deduplicate_results(merged, threshold=0.7, lang_hint=lang_hint, query=query)
    return deduped[:limit]
