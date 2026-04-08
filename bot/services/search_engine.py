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
_NON_ORIGINAL_MARKERS: tuple[tuple[str, float], ...] = (
    # Hard penalties — clearly not the original
    ("кавер", 0.35),
    ("cover", 0.35),
    ("karaoke", 0.38),
    ("караоке", 0.38),
    ("минус", 0.40),
    ("минусовка", 0.40),
    ("instrumental", 0.42),
    ("инструментал", 0.42),
    # Medium penalties — likely reuploads/modifications
    ("remix", 0.50),
    ("ремикс", 0.50),
    ("speed up", 0.42),
    ("slowed", 0.48),
    ("reverb", 0.48),
    ("bass boost", 0.45),
    ("bassboosted", 0.45),
    ("8d audio", 0.45),
    ("8d", 0.50),
    ("nightcore", 0.42),
    ("tiktok", 0.50),
    ("тикток", 0.50),
    ("live", 0.62),
    ("концерт", 0.58),
    ("живое исполнение", 0.58),
    ("acoustic", 0.62),
    ("tribute", 0.60),
    ("ost", 0.55),
    ("soundtrack", 0.55),
    ("саундтрек", 0.55),
    ("из фильма", 0.42),
    ("сцена из фильма", 0.38),
    ("from the film", 0.42),
    ("from movie", 0.42),
    # Soft penalties — text/lyrics content, not the track itself
    ("lyrics", 0.45),
    ("lyric", 0.45),
    ("with lyrics", 0.42),
    ("official lyrics", 0.40),
    ("текст песни", 0.45),
    ("текст и перевод", 0.42),
    ("слова песни", 0.42),
    ("текст", 0.55),
)


def normalize_query(query: str) -> str:
    """Normalize a search query: strip junk, normalize whitespace, lowercase."""
    q = query.strip().lower()
    q = q.replace("'", "").replace("’", "").replace("`", "")
    q = _JUNK_RE.sub(" ", q)
    q = _MULTI_SPACE.sub(" ", q)
    return q.strip()


# ── Smart query parsing ──────────────────────────────────────────────────

# Stop-words users add but that hurt search accuracy
_QUERY_STOP_WORDS = frozenset({
    "песня", "песню", "песни", "скачать", "слушать", "слушай", "найди", "найти",
    "музыка", "музыку", "трек", "включи", "включить", "поставь",
    "download", "listen", "play", "song", "music", "track", "audio",
    "пожалуйста", "плиз", "please", "бот", "bot", "щас", "сейчас", "now",
})

# Separators between artist and title
_ARTIST_SEP_RE = re.compile(r"\s*[-–—]\s*")


def parse_query(raw_query: str) -> dict:
    """Parse user query into structured form.

    Returns dict with keys:
        clean: query with stop-words removed
        artist_hint: extracted artist (if dash separator found), or None
        title_hint: extracted title part (if dash separator found), or None
        original: original normalized query
    """
    norm = normalize_query(raw_query)

    # Remove stop-words (only if they don't eat the entire query)
    words = norm.split()
    cleaned = [w for w in words if w not in _QUERY_STOP_WORDS]
    if not cleaned:
        cleaned = words  # fallback: keep everything
    clean = " ".join(cleaned)

    # Try to split "artist - title"
    artist_hint = None
    title_hint = None
    parts = _ARTIST_SEP_RE.split(raw_query.strip(), maxsplit=1)
    if len(parts) == 2:
        a, t = parts[0].strip(), parts[1].strip()
        if len(a) >= 2 and len(t) >= 2:
            artist_hint = normalize_query(a)
            title_hint = normalize_query(t)

    return {
        "clean": clean,
        "artist_hint": artist_hint,
        "title_hint": title_hint,
        "original": norm,
    }


def _non_original_penalty(query_norm: str, track_text: str) -> float:
    """Demote cover/karaoke/lyrics variants unless user explicitly asked for them.

    For short queries (<=3 words), penalties are harsher because users almost
    certainly want the original.
    """
    short_query = len(query_norm.split()) <= 3
    penalty = 1.0
    for marker, factor in _NON_ORIGINAL_MARKERS:
        if marker in track_text and marker not in query_norm:
            effective = factor * 0.6 if short_query else factor
            penalty = min(penalty, effective)
    return penalty


def _token_set_sim(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if _rf_fuzz is not None:
        return float(_rf_fuzz.token_set_ratio(a, b)) / 100.0
    return _jaccard_similarity(a, b)


def _stuffed_title_penalty(query_words: list[str], artist_lower: str, title_lower: str, raw_coverage: float) -> float:
    """Demote reuploads where another artist name is stuffed into the title prefix.

    Example: uploader="stiven ...", title="пропаганда яй я яблоки ела".
    """
    if raw_coverage < 0.75:
        return 1.0

    query_set = set(query_words)
    title_words = title_lower.split()
    prefix_words: list[str] = []
    for word in title_words:
        if word in query_set:
            break
        if len(word) > 2:
            prefix_words.append(word)
        if len(prefix_words) >= 3:
            break

    if not prefix_words:
        return 1.0

    prefix_text = " ".join(prefix_words)
    if _token_set_sim(artist_lower, prefix_text) >= 0.45:
        return 1.0

    return 0.62


def _query_echo_penalty(query_norm: str, query_words: list[str], artist_lower: str, title_lower: str, raw_coverage: float) -> float:
    """Demote uploads where the title mostly parrots the lyric fragment itself.

    These are often user uploads, shorts, or lyric videos rather than the canonical track.
    """
    if len(query_words) < 3:
        return 1.0

    title_words = title_lower.split()
    if not title_words:
        return 1.0

    meaningful_query = {w for w in query_words if len(w) > 2}
    artist_overlap = len(meaningful_query & set(artist_lower.split()))
    extra_words = max(0, len(title_words) - len(query_words))
    query_compact = query_norm.replace(" ", "")
    title_compact = title_lower.replace(" ", "")
    has_marker = any(
        marker in title_lower
        for marker in (
            "lyrics", "lyric", "текст", "слова", "cover", "кавер",
            "speed up", "slowed", "remix", "ремикс",
        )
    )
    title_sim = _token_set_sim(query_norm, title_lower)

    if artist_overlap > 0:
        return 1.0

    if title_compact == query_compact and len(query_words) >= 4:
        return 0.5

    if query_compact and query_compact in title_compact:
        if extra_words >= 3:
            return 0.38 if has_marker else 0.48
        if extra_words >= 1:
            return 0.55 if has_marker else 0.68

    if title_sim >= 0.82 and extra_words >= 1:
        return 0.52 if has_marker else 0.7

    if raw_coverage >= 0.95 and extra_words >= 4:
        return 0.62

    return 1.0


def is_query_echo_title(query: str, artist: str, title: str) -> bool:
    """Return True when the title mostly parrots the user query.

    Used to decide whether we should try alternative transliterated searches.
    """
    query_norm = normalize_query(query)
    artist_norm = normalize_query(artist)
    title_norm = normalize_query(title)
    if not query_norm or not title_norm:
        return False

    compact_query = query_norm.replace(" ", "")
    compact_title = title_norm.replace(" ", "")
    meaningful_query = {word for word in query_norm.split() if len(word) > 2}
    artist_overlap = len(meaningful_query & set(artist_norm.split()))
    title_sim = _token_set_sim(query_norm, title_norm)

    if compact_query == compact_title and len(query_norm.split()) >= 3:
        return artist_overlap == 0
    if compact_query and compact_query in compact_title and artist_overlap == 0:
        return True
    return artist_overlap == 0 and title_sim >= 0.82 and len(query_norm.split()) >= 3


def _artist_repeated_in_title_penalty(artist_lower: str, title_lower: str) -> float:
    """Demote uploads that repeat the uploader name inside a long title."""
    artist_tokens = [token for token in artist_lower.split() if len(token) > 2]
    title_tokens = title_lower.split()
    if len(artist_tokens) < 1 or len(title_tokens) < 6:
        return 1.0

    prefix = " ".join(title_tokens[:min(len(title_tokens), len(artist_tokens) + 2)])
    if _token_set_sim(artist_lower, prefix) >= 0.7:
        return 0.52
    return 1.0


def _translit_match_bonus(query_norm: str, artist_lower: str, title_lower: str) -> float:
    """Boost canonical Latin/Cyrillic matches for transliterated lyric queries."""
    query_script = detect_script(query_norm)
    if query_script == "mixed":
        return 0.0

    track_text = f"{artist_lower} {title_lower}"
    track_script = detect_script(track_text)
    if query_script == track_script:
        return 0.0

    variants: list[str] = []
    if query_script == "cyrillic":
        variants.append(normalize_query(transliterate_lat_to_cyr(track_text)))
        variants.append(normalize_query(transliterate_lat_to_cyr(title_lower)))
    elif query_script == "latin":
        variants.append(normalize_query(transliterate_cyr_to_lat(track_text)))
        variants.append(normalize_query(transliterate_cyr_to_lat(title_lower)))

    best = 0.0
    for variant in variants:
        if variant:
            best = max(best, _token_set_sim(query_norm, variant))
            if _rf_fuzz is not None:
                best = max(
                    best,
                    float(_rf_fuzz.partial_ratio(query_norm.replace(" ", ""), variant.replace(" ", ""))) / 100.0,
                )

    if best < 0.35:
        return 0.0
    return min(0.75, best * 0.75)


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


def _relevance_score(query_norm: str, artist: str, title: str, position: int = 0, parsed: dict | None = None) -> float:
    """Score how relevant a track is to the search query (0.0 - 3.0+).

    Multi-signal scoring:
    1. Word overlap (exact + substring) — primary signal, weighted x1.5
    2. Artist match bonus
    3. Position bonus (match at start of title/artist)
    4. RapidFuzz token_sort_ratio (catches typos & word reorder) — capped at 0.3
    5. Title brevity bonus
    6. Provider position bonus
    7. Coverage penalty — if <40% of query words found, heavy penalty
    8. Explicit artist-title split bonus (when query contains "artist - title")
    """
    query_words = query_norm.split()
    if not query_words:
        return 0.0
    query_set = set(query_words)
    # Filter out very short stop-words for coverage calc (на, в, и, ...)
    _meaningful = {w for w in query_set if len(w) > 2}

    artist_lower = normalize_query(artist)
    title_lower = normalize_query(title)
    track_text = f"{artist_lower} {title_lower}"
    track_words = set(track_text.split())

    # 1. Word overlap (0.0 - 1.5) — primary signal
    exact = len(query_set & track_words)
    substring = 0
    for qw in query_set - track_words:
        if qw in track_text:
            substring += 0.5
    raw_coverage = (exact + substring) / len(query_words)
    word_score = raw_coverage * 1.5

    # 2. Artist match bonus (0.0 - 0.4)
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

    # 4. RapidFuzz bonus (0.0 - 0.3): catches typos and word reorder (capped)
    fuzz_bonus = 0.0
    if _rf_fuzz is not None:
        ratio = float(_rf_fuzz.token_sort_ratio(query_norm, track_text)) / 100.0
        fuzz_bonus = ratio * 0.3

    # 5. Title brevity bonus (0.0 - 0.1): shorter titles = more precise match
    total_words = len(track_text.split())
    if total_words > 0:
        brevity = max(0.0, 1.0 - (total_words - len(query_words)) / 10.0)
        brevity_bonus = brevity * 0.1
    else:
        brevity_bonus = 0.0

    # 6. Provider position bonus (0.0 - 0.3): first results from provider are more relevant
    provider_bonus = max(0.0, 0.3 - position * 0.03)

    # 6b. Transliteration bonus: helps when users type foreign lyrics in Cyrillic or vice versa
    translit_bonus = _translit_match_bonus(query_norm, artist_lower, title_lower)

    base = word_score + artist_bonus + position_bonus + fuzz_bonus + brevity_bonus + provider_bonus + translit_bonus

    # 7. Coverage penalty: for queries with 3+ meaningful words,
    #    penalise tracks where query words are mostly missing.
    #    Continuous: coverage 1.0 → no penalty, 0.5 → ×0.7, 0.0 → ×0.3
    if len(_meaningful) >= 3:
        found_meaningful = 0
        for w in _meaningful:
            if w in track_words:
                found_meaningful += 1
            elif w in track_text:
                found_meaningful += 0.7  # substring match counts partially
        meaningful_ratio = found_meaningful / len(_meaningful)
        if meaningful_ratio < 0.7:
            penalty = 0.3 + meaningful_ratio  # 0.3 .. 1.0
            base *= penalty

    base *= _non_original_penalty(query_norm, track_text)
    base *= _stuffed_title_penalty(query_words, artist_lower, title_lower, raw_coverage)
    base *= _query_echo_penalty(query_norm, query_words, artist_lower, title_lower, raw_coverage)
    base *= _artist_repeated_in_title_penalty(artist_lower, title_lower)

    # 8. Explicit "artist - title" bonus: when user typed "Кино - Группа крови"
    if parsed and parsed.get("artist_hint") and parsed.get("title_hint"):
        a_sim = _token_set_sim(parsed["artist_hint"], artist_lower)
        t_sim = _token_set_sim(parsed["title_hint"], title_lower)
        if a_sim >= 0.75 and t_sim >= 0.6:
            base += 0.5 * (a_sim + t_sim) / 2  # up to +0.5

    return base


def deduplicate_results(results: list[dict], threshold: float = 0.7, lang_hint: str = "mixed", query: str = "") -> list[dict]:
    """Remove duplicate tracks, keeping the one from the best source.
    Then re-rank by relevance to the original query."""
    if not results:
        return []

    # Parse query for structured matching
    parsed = parse_query(query) if query else None

    # Pick ranking table based on query language
    if lang_hint == "cyrillic":
        rank = _SOURCE_RANK_CYR
    elif lang_hint == "latin":
        rank = _SOURCE_RANK_LAT
    else:
        rank = _SOURCE_RANK

    # Sort by source quality (best first) for dedup — keep best source version
    ranked = sorted(results, key=lambda r: rank.get(r.get("source", ""), 0), reverse=True)

    # Pre-compute relevance if query is available (used for smarter dedup)
    query_norm = normalize_query(query) if query else ""

    kept: list[dict] = []
    kept_keys: list[str] = []

    for track in ranked:
        key = _normalize_for_dedup(
            track.get("uploader", ""),
            track.get("title", ""),
        )
        is_dup = False
        for idx, existing_key in enumerate(kept_keys):
            # Use rapidfuzz token_sort_ratio if available (better than Jaccard for music titles)
            if _rf_fuzz is not None:
                sim = float(_rf_fuzz.token_sort_ratio(key, existing_key)) / 100.0
            else:
                sim = _jaccard_similarity(key, existing_key)
            if sim >= threshold:
                is_dup = True
                # Smart merge: if the new duplicate has a significantly better
                # title match to the query, replace the kept version
                if query_norm:
                    old_score = _relevance_score(
                        query_norm,
                        kept[idx].get("uploader", ""),
                        kept[idx].get("title", ""),
                        position=kept[idx].get("_provider_pos", 5),
                        parsed=parsed,
                    ) + float(kept[idx].get("_hint_bonus", 0.0))
                    new_score = _relevance_score(
                        query_norm,
                        track.get("uploader", ""),
                        track.get("title", ""),
                        position=track.get("_provider_pos", 5),
                        parsed=parsed,
                    ) + float(track.get("_hint_bonus", 0.0))
                    if new_score > old_score + 0.15:
                        # Keep better-matching version (preserve source/file_id from old if available)
                        if kept[idx].get("file_id") and not track.get("file_id"):
                            track["file_id"] = kept[idx]["file_id"]
                        kept[idx] = track
                        kept_keys[idx] = key
                break
        if not is_dup:
            kept.append(track)
            kept_keys.append(key)

    # Re-rank by relevance to original query
    if query:
        query_norm = normalize_query(query)
        artist_counts: dict[str, int] = {}
        for track in kept:
            artist_key = normalize_query(track.get("uploader", ""))
            if artist_key:
                artist_counts[artist_key] = artist_counts.get(artist_key, 0) + 1
        kept.sort(
            key=lambda t: (
                _relevance_score(
                    query_norm,
                    t.get("uploader", ""),
                    t.get("title", ""),
                    position=t.get("_provider_pos", 5),
                    parsed=parsed,
                )
                + float(t.get("_hint_bonus", 0.0))
                # Popularity micro-boost: tracks already in our cache are proven popular
                + (0.05 if t.get("file_id") else 0.0),
                + (0.28 * max(0, artist_counts.get(normalize_query(t.get("uploader", "")), 0) - 1)),
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
