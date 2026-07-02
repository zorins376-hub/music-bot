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
    q = q.replace("‘", "").replace("’", "").replace("`", "")
    q = re.sub(r'\s*[\(\[][^\)\]]{0,50}[\)\]]\s*', ' ', q)
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

# Second token in a query rarely belongs to a multi-word artist name.
_TITLEISH_SECOND_WORDS = frozenset({
    "это", "моя", "мой", "мое", "наша", "наш", "как", "для", "нет", "все", "ещё", "eще",
    "теперь", "было", "буду", "будет", "очень", "просто", "только", "если", "когда",
    "люблю", "любит", "хочу", "хочет", "был", "была", "были",
})

# Cyrillic nicknames / stage tokens → latin fragments common in artist names
_STAGE_LAT_FRAGMENTS: dict[str, tuple[str, ...]] = {
    "принц": ("prince",),
    "асха": ("asx", "asxa", "asxab"),
    "macan": ("macan",),
    "матранг": ("matrang", "matr", "matang"),
}

# Query starters that indicate lyrics, not "artist + title"
_LYRIC_LEAD_WORDS = frozenset({
    "я", "ты", "мы", "он", "она", "они", "вы", "не", "ни", "в", "на", "с", "к", "у", "o",
    "и", "a", "но", "да", "нет", "дай", "если", "когда", "где", "что", "как", "всё", "все",
    "это", "тот", "та", "те", "those", "this", "the", "when", "where", "why", "how",
    "никуда", "ничего", "никто", "всегда", "никогда", "теперь", "потом", "снова",
    "хочется", "хочу", "хочет", "любит", "люблю", "жить", "живу",
})

# Separators between artist and title
_ARTIST_SEP_RE = re.compile(r"\s*[-–—]\s*")

# Misheard lyric/slang pairs — not "artist + title" (кока лова ≠ Клава Кока)
_FALSE_TITLE_TRANSLIT = frozenset({"лова", "lova", "love", "luv"})
_FALSE_ARTIST_FRAGMENTS = frozenset({"кока", "coca", "koka", "коко"})

_QUERY_SEARCH_ALIASES: dict[str, list[str]] = {}

_KOKA_LOVA_QUERY_FORMS = frozenset({"кока лова", "лова кока", "koka lova"})


def _is_false_artist_title_split(artist: str, title: str) -> bool:
    """Detect mis-parsed slang fragments like «кока лова» (≠ Клава Кока as artist)."""
    a, t = normalize_query(artist), normalize_query(title)
    if a in _FALSE_ARTIST_FRAGMENTS and t in _FALSE_TITLE_TRANSLIT:
        return True
    if a in _FALSE_TITLE_TRANSLIT and t in _FALSE_ARTIST_FRAGMENTS:
        return True
    if len(a) <= 4 and len(t) <= 4 and t in _FALSE_TITLE_TRANSLIT:
        return True
    return False


def get_query_search_aliases(query: str) -> list[str]:
    """Extra provider queries for common misheard / Cyrillic→Latin fragments."""
    from bot.services.search_curated import query_search_aliases

    return query_search_aliases(query)


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

    words = clean.split()

    # Two-word Cyrillic: "матранг рука", "104 приезжай", or full name "леонид портной"
    if not artist_hint and len(words) == 2 and detect_script(clean) == "cyrillic":
        a, t = words[0], words[1]
        if (
            len(a) >= 5 and len(t) >= 5
            and a not in _QUERY_STOP_WORDS
            and a not in _LYRIC_LEAD_WORDS
        ):
            # Both tokens long → likely "first last" artist without a title token.
            artist_hint = f"{a} {t}"
            title_hint = None
        elif len(a) >= 3 and len(t) >= 3 and a not in _QUERY_STOP_WORDS:
            if not _is_false_artist_title_split(a, t):
                artist_hint = a
                title_hint = t

    # Stage name + short title tail: "асха принц су"
    if not artist_hint and len(words) == 3 and detect_script(clean) == "cyrillic":
        a, b, t = words[0], words[1], words[2]
        if (
            len(t) <= 4
            and len(a) >= 3
            and len(b) >= 3
            and a not in _QUERY_STOP_WORDS
            and a not in _LYRIC_LEAD_WORDS
            and b not in _TITLEISH_SECOND_WORDS
        ):
            artist_hint = f"{a} {b}"
            title_hint = t if len(t) >= 2 else None

    # Multi-word Cyrillic: "асха принц голодная собака" → artist + title tail
    if not artist_hint and len(words) >= 4 and detect_script(clean) == "cyrillic":
        first = words[0]
        if (
            first not in _QUERY_STOP_WORDS
            and first not in _LYRIC_LEAD_WORDS
            and words[1] not in _TITLEISH_SECOND_WORDS
        ):
            artist_hint = f"{words[0]} {words[1]}"
            title_hint = " ".join(words[2:])

    # Space-separated "artist title…" (no dash): common in Cyrillic group queries
    if not artist_hint and len(words) >= 3:
        first = words[0]
        if (
            len(first) >= 4
            and first not in _QUERY_STOP_WORDS
            and first not in _LYRIC_LEAD_WORDS
            and detect_script(clean) == "cyrillic"
        ):
            artist_hint = first
            title_hint = " ".join(words[1:])

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


def _leading_artist_title_bonus(
    query_words: list[str], artist_lower: str, title_lower: str, parsed: dict | None,
) -> float:
    """Boost when query leads with artist name and remainder matches title."""
    if len(query_words) < 2:
        return 0.0

    artist_hint = (parsed or {}).get("artist_hint")
    title_hint = (parsed or {}).get("title_hint")
    if artist_hint and title_hint:
        lead = artist_hint
        rest = title_hint
    else:
        lead = query_words[0]
        rest = " ".join(query_words[1:])

    if len(lead) < 3 or not rest:
        return 0.0

    artist_sim = _artist_tokens_match(lead, artist_lower)
    if artist_sim < 0.72 and lead not in artist_lower:
        return 0.0

    title_sim = _token_set_sim(rest, title_lower)
    if title_sim < 0.55 and rest not in title_lower:
        partial = 0.0
        if _rf_fuzz is not None:
            partial = float(_rf_fuzz.partial_ratio(rest, title_lower)) / 100.0
        if partial < 0.62:
            # Allow one typo in title tail (гододная → голодная)
            rest_words = [w for w in rest.split() if len(w) > 2]
            if rest_words:
                matched = sum(1 for w in rest_words if _hint_word_in_title(w, title_lower))
                if matched / len(rest_words) < 0.5:
                    return 0.0
            else:
                return 0.0
    else:
        partial = 0.0
        if _rf_fuzz is not None:
            partial = float(_rf_fuzz.partial_ratio(rest, title_lower)) / 100.0

    return min(0.85, 0.35 * artist_sim + 0.45 * max(title_sim, partial))


def query_word_coverage(
    query_norm: str,
    artist: str,
    title: str,
    *,
    title_only: bool = False,
) -> float:
    """Share of meaningful query words found in track metadata (0.0–1.0)."""
    meaningful = [w for w in query_norm.split() if len(w) > 2]
    if not meaningful:
        return 1.0
    blob = normalize_query(title if title_only else f"{artist} {title}")
    if not blob:
        return 0.0
    found = 0.0
    for word in meaningful:
        if word in blob.split():
            found += 1.0
        elif word in blob:
            found += 0.7
        elif _rf_fuzz is not None:
            ratio = float(_rf_fuzz.partial_ratio(word, blob)) / 100.0
            if ratio >= 0.88 or (len(word) >= 5 and ratio >= 0.72):
                found += 0.6
    return found / len(meaningful)


def _hint_word_in_title(word: str, title_lower: str) -> bool:
    """Check title-hint word against title tokens, including morphological variants (рука/руки)."""
    tokens = title_lower.split()
    if word in tokens:
        return True
    if len(word) >= 4:
        for tok in tokens:
            if tok.startswith(word):  # кока → кокаина
                return True
    if len(word) >= 3:
        # Cyrillic/Russian inflection: shared 3-char stem (рука → руки, руке, руку)
        stem = word if len(word) <= 3 else word[:-1]
        if len(stem) >= 3:
            for tok in tokens:
                if tok.startswith(stem):
                    return True
    if _rf_fuzz is None:
        return False
    for tok in tokens:
        if len(word) >= 3 and len(tok) >= 3:
            ratio = float(_rf_fuzz.ratio(word, tok)) / 100.0
            if ratio >= 0.78:
                return True
            # Single-char typo in long words: гододная ↔ голодная
            if len(word) >= 5 and len(tok) >= 5 and ratio >= 0.71:
                return True
            # partial_ratio only when token is long enough (avoid воспоминанье ↔ помню)
            if len(tok) >= max(4, int(len(word) * 0.65)):
                if float(_rf_fuzz.partial_ratio(word, tok)) / 100.0 >= 0.88:
                    return True
    return False


def _artist_token_in_name(tok: str, artist_lower: str) -> bool:
    """Whether a query token matches any fragment of the artist name."""
    if not tok or not artist_lower:
        return False
    if tok in artist_lower:
        return True
    lat = transliterate_cyr_to_lat(tok)
    compact = artist_lower.replace(" ", "").replace("$", "").replace(".", "")
    if len(lat) >= 3 and lat in compact:
        return True
    for frag in _STAGE_LAT_FRAGMENTS.get(tok, ()):
        if frag in compact:
            return True
    if _rf_fuzz is None:
        return False
    parts = re.split(r"[\s$\.]+", artist_lower)
    for part in parts:
        if len(part) < 2:
            continue
        ratio = float(_rf_fuzz.ratio(tok, part)) / 100.0
        if ratio >= 0.78:
            return True
        if len(tok) >= 5 and ratio >= 0.71:
            return True
        if len(lat) >= 3 and float(_rf_fuzz.ratio(lat, part)) / 100.0 >= 0.78:
            return True
    if float(_rf_fuzz.partial_ratio(tok, artist_lower)) / 100.0 >= 0.82:
        return True
    if len(lat) >= 3 and float(_rf_fuzz.partial_ratio(lat, artist_lower)) / 100.0 >= 0.85:
        return True
    return False


def _artist_tokens_match(query_artist: str, artist_lower: str) -> float:
    """Fuzzy match for multi-word artist names and stage aliases (асха принц → PRiNCE)."""
    if not query_artist or not artist_lower:
        return 0.0
    sim = _token_set_sim(query_artist, artist_lower)
    if sim >= 0.72 or query_artist in artist_lower:
        return sim
    q_tokens = [t for t in query_artist.split() if len(t) > 2]
    if not q_tokens:
        return sim
    hits = 0.0
    for tok in q_tokens:
        if _artist_token_in_name(tok, artist_lower):
            hits += 1.0
            continue
        if _rf_fuzz is not None:
            for part in artist_lower.replace("$", " ").replace(".", " ").split():
                if len(part) > 2 and float(_rf_fuzz.ratio(tok, part)) / 100.0 >= 0.78:
                    hits += 1.0
                    break
            else:
                if float(_rf_fuzz.partial_ratio(tok, artist_lower)) / 100.0 >= 0.85:
                    hits += 0.85
    if q_tokens:
        return max(sim, hits / len(q_tokens))
    return sim


def _parsed_artist_mismatch_penalty(
    parsed: dict | None,
    artist_lower: str,
    title_lower: str,
) -> float:
    """Demote title-echo tracks when parsed artist doesn't match (Скриптонit ≠ $UICIDEKID)."""
    if not parsed or not parsed.get("artist_hint"):
        return 1.0
    ah = parsed["artist_hint"]
    if _artist_tokens_match(ah, artist_lower) >= 0.45:
        return 1.0
    th = parsed.get("title_hint") or ""
    if th and _token_set_sim(th, title_lower) >= 0.45:
        return 0.1
    if th:
        return 0.25
    return 1.0


def _false_artist_fragment_penalty(query_norm: str, artist_lower: str, title_lower: str) -> float:
    """Demote «Клава Кока» on «кока лова» when title isn't the intended drug/lyric track."""
    for word in query_norm.split():
        if word not in _FALSE_ARTIST_FRAGMENTS:
            continue
        in_artist = word in artist_lower
        in_title = any(
            tok.startswith(word) or word in tok
            for tok in title_lower.split()
        )
        if in_artist and not in_title:
            return 0.1
    return 1.0


def _fragment_title_stem_bonus(query_norm: str, title_lower: str) -> float:
    """Boost «Koka Lova» title when user typed «кока лова» / koka lova."""
    q_words = query_norm.split()
    has_koka = any(w in _FALSE_ARTIST_FRAGMENTS or w in {"koka", "coca"} for w in q_words)
    has_lova = any(w in _FALSE_TITLE_TRANSLIT for w in q_words)
    if has_koka and has_lova:
        title_has_koka = "koka" in title_lower or "кока" in title_lower
        title_has_lova = "lova" in title_lower or "лова" in title_lower
        if title_has_koka and title_has_lova:
            return 1.4
        # «Кока-Кола» etc. — only partial «кока» match, no «lova»
        if title_has_koka and not title_has_lova:
            return -0.5
        return 0.0
    for word in q_words:
        if word not in _FALSE_ARTIST_FRAGMENTS:
            continue
        for tok in title_lower.split():
            if len(tok) > len(word) and tok.startswith(word):
                return 0.95
    return 0.0


def _title_rare_word_bonus(query_norm: str, title_lower: str) -> float:
    """Boost when a distinctive query word (e.g. 'кокаина') appears in the title."""
    rare = [w for w in query_norm.split() if len(w) >= 5]
    if not rare:
        return 0.0
    title_tokens = title_lower.split()
    for word in rare:
        for tok in title_tokens:
            if word == tok:
                return 0.85
            if _hint_word_in_title(word, tok):
                return 0.65
            if _rf_fuzz is not None and float(_rf_fuzz.ratio(word, tok)) / 100.0 >= 0.82:
                return 0.55
    return 0.0


def _title_keyword_from_query_bonus(query_norm: str, title_lower: str) -> float:
    """Boost when the track title is essentially one keyword from the lyric query."""
    title_tokens = [t for t in title_lower.split() if len(t) >= 5]
    if not title_tokens or len(title_tokens) > 3:
        return 0.0
    q_words = [w for w in query_norm.split() if len(w) >= 5]
    if len(q_words) < 1:
        return 0.0
    for tok in title_tokens:
        if tok in q_words:
            return 0.9
        if any(_hint_word_in_title(tok, w) or _hint_word_in_title(w, tok) for w in q_words):
            return 0.75
    return 0.0


def _lyric_distinctive_miss_penalty(query_norm: str, title_lower: str, parsed: dict | None) -> float:
    """Penalise lyric queries where distinctive words never appear in the title."""
    if not is_lyric_like_query(query_norm, parsed):
        return 1.0
    distinctive = [w for w in query_norm.split() if len(w) >= 6]
    if not distinctive:
        return 1.0
    title_tokens = title_lower.split()
    for w in distinctive:
        if w in title_tokens:
            continue
        if _rf_fuzz is not None:
            best = max(
                (float(_rf_fuzz.ratio(w, tok)) / 100.0 for tok in title_tokens if len(tok) >= 4),
                default=0.0,
            )
            if best >= 0.82:
                continue
        return 0.15
    return 1.0


def query_title_hint_coverage(
    query_norm: str,
    title: str,
    parsed: dict | None = None,
) -> float:
    """Coverage of title-hint words (or full query) against track title."""
    parsed = parsed or {}
    title_hint = parsed.get("title_hint")
    if title_hint:
        words = [w for w in normalize_query(title_hint).split() if len(w) > 2]
    else:
        words = [w for w in query_norm.split() if len(w) > 2]
    if not words:
        return 1.0
    blob = normalize_query(title)
    if not blob:
        return 0.0
    found = 0.0
    for word in words:
        if _hint_word_in_title(word, blob):
            found += 1.0

    return found / len(words)


def is_lyric_like_query(query: str, parsed: dict | None = None) -> bool:
    """True when the query looks like a lyric fragment rather than artist/title."""
    norm = normalize_query(query)
    words = [w for w in norm.split() if len(w) > 2]
    if len(words) < 2:
        return False

    parsed = parsed or parse_query(query)
    artist_hint = parsed.get("artist_hint")
    title_hint = parsed.get("title_hint")

    # Explicit "artist - title" is not a raw lyric search.
    if artist_hint and title_hint and " - " in (query or ""):
        return False

    # Full-name artist query without a title token (леонид портной).
    if artist_hint and not title_hint and " " in artist_hint:
        return False

    # Structured artist + title tail (асха принц голодная собака) — not raw lyrics.
    if artist_hint and title_hint and " " in artist_hint:
        if artist_hint.split()[0] not in _LYRIC_LEAD_WORDS:
            return False

    # Long multi-word fragments without artist structure → lyrics.
    if len(words) >= 4 and not artist_hint:
        return True

    # Two/three words where the tail looks like a title or lyric fragment.
    if artist_hint and title_hint and len(title_hint.split()) <= 3:
        if " " not in artist_hint and artist_hint.split()[0] not in _LYRIC_LEAD_WORDS:
            return False
        return True

    # Two-word fragments without artist structure → lyric / misheard search.
    if len(words) == 2 and not artist_hint:
        return True

    # No artist split but 3+ words → likely lyrics from memory.
    if not artist_hint and len(words) >= 3:
        return True

    return False


def extract_distinctive_lyric_words(query: str) -> list[str]:
    """Long / rare tokens from a lyric fragment (for fallback provider search)."""
    norm = normalize_query(query)
    words = [w for w in norm.split() if len(w) >= 5 and w not in _QUERY_STOP_WORDS]
    # Prefer longer distinctive words first (кокаина, воспоминанье).
    return sorted(dict.fromkeys(words), key=len, reverse=True)


def lyric_search_variants(query: str, parsed: dict | None = None) -> list[str]:
    """Alternate phrasings to try against lyrics DB and provider fallback."""
    norm = normalize_query(query)
    if not norm:
        return []

    parsed = parsed or parse_query(query)
    words = norm.split()
    variants: list[str] = [norm]

    stripped = [
        w for w in words
        if w not in _LYRIC_LEAD_WORDS and w not in _QUERY_STOP_WORDS and len(w) > 2
    ]
    if stripped:
        tail = " ".join(stripped)
        if tail != norm and len(tail) >= 4:
            variants.append(tail)

    if len(words) >= 3:
        tail3 = " ".join(words[-3:])
        if tail3 != norm:
            variants.append(tail3)

    for w in extract_distinctive_lyric_words(query)[:2]:
        variants.append(w)

    seen: set[str] = set()
    out: list[str] = []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def needs_lyrics_search_boost(
    query: str,
    top_track: dict | None,
    *,
    parsed: dict | None = None,
) -> bool:
    """Decide whether to enrich results via lyrics databases (Genius/Musixmatch)."""
    if not query.strip():
        return False
    parsed = parsed or parse_query(query)
    qn = normalize_query(query)

    if is_lyric_like_query(query, parsed):
        if not top_track:
            return True
        title_cov = query_title_hint_coverage(
            qn,
            top_track.get("title", ""),
            parsed,
        )
        total_cov = query_word_coverage(
            qn,
            top_track.get("uploader", ""),
            top_track.get("title", ""),
        )
        if title_cov >= 0.65 and total_cov >= 0.75:
            return False
        if title_cov < 0.65 or total_cov < 0.75:
            return True
        score = _relevance_score(
            qn,
            top_track.get("uploader", ""),
            top_track.get("title", ""),
            position=top_track.get("_provider_pos", 5),
            parsed=parsed,
        )
        return score < 2.2

    if not top_track:
        return len(qn.split()) >= 4

    if parsed.get("artist_hint") and parsed.get("title_hint"):
        title_cov = query_title_hint_coverage(
            qn, top_track.get("title", ""), parsed,
        )
        if title_cov < 0.5:
            return True

    total_cov = query_word_coverage(
        qn,
        top_track.get("uploader", ""),
        top_track.get("title", ""),
    )
    return total_cov < 0.55 and len(qn.split()) >= 3


def _missing_title_words_penalty(
    query_words: list[str],
    title_lower: str,
    artist_lower: str,
    parsed: dict | None,
) -> float:
    """Penalise when user-specified title words are absent from the track title."""
    title_hint = (parsed or {}).get("title_hint")
    tail_words: list[str]
    if title_hint:
        tail_words = [w for w in title_hint.split() if len(w) > 2]
    elif len(query_words) >= 2:
        tail_words = [w for w in query_words[1:] if len(w) > 2]
    else:
        return 1.0

    if not tail_words:
        return 1.0

    missing = 0
    for word in tail_words:
        if word in artist_lower:
            continue
        if _hint_word_in_title(word, title_lower):
            continue
        missing += 1

    if missing == 0:
        return 1.0
    ratio = missing / len(tail_words)
    if ratio >= 1.0:
        return 0.42
    if ratio >= 0.5:
        return 0.62
    return 0.82


def _title_hint_exact_bonus(parsed: dict | None, artist_lower: str, title_lower: str) -> float:
    """Large bonus when track title matches parsed title_hint (e.g. 'рука' -> 'Рука')."""
    if not parsed:
        return 0.0
    title_hint = parsed.get("title_hint")
    artist_hint = parsed.get("artist_hint")
    if not title_hint:
        return 0.0
    th = normalize_query(title_hint)
    if not _hint_word_in_title(th, title_lower) and th != title_lower:
        if th not in title_lower.split() and not title_lower.startswith(th):
            return 0.0
    bonus = 0.75 if th == title_lower or title_lower.split()[0:1] == [th] else 0.55
    if artist_hint:
        if _artist_tokens_match(artist_hint, artist_lower) >= 0.5 or artist_hint in artist_lower:
            bonus += 0.35
    return bonus


def _title_exact_bonus(query_words: list[str], title_lower: str) -> float:
    """Prefer tracks whose title contains the query tail (after artist token)."""
    if len(query_words) < 3:
        return 0.0
    tail = " ".join(query_words[1:])
    if len(tail) < 5:
        return 0.0
    if tail in title_lower:
        return 0.25
    if _rf_fuzz is not None:
        ratio = float(_rf_fuzz.partial_ratio(tail, title_lower)) / 100.0
        if ratio >= 0.88:
            return 0.18
    return 0.0


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
# YouTube is intentionally the LOWEST-ranked source: it is the most fragile (bot
# detection, LOGIN_REQUIRED, throttling) and we only fall back to it when no
# downloadable Yandex/VK/Deezer/Spotify match exists. Local channel cache wins everywhere.
_SOURCE_RANK = {"channel": 6, "yandex": 5, "vk": 4, "deezer": 4, "spotify": 3, "apple": 3, "soundcloud": 2, "youtube": 1}
# Language-aware: Russian queries strongly prefer Yandex/VK (native catalogs).
_SOURCE_RANK_CYR = {"channel": 7, "yandex": 6, "vk": 5, "deezer": 4, "spotify": 3, "apple": 3, "soundcloud": 2, "youtube": 1}
# Latin queries: still prefer Yandex/Deezer/Spotify (they download cleanly via providers);
# YouTube last because it routes through WARP and is rate-limited by Google.
_SOURCE_RANK_LAT = {"channel": 7, "yandex": 5, "spotify": 5, "deezer": 5, "apple": 4, "vk": 4, "soundcloud": 3, "youtube": 1}


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

    # 2. Artist match bonus (0.0 - 0.55)
    artist_bonus = 0.0
    artist_words = set(artist_lower.split())
    if artist_words and query_set:
        artist_overlap = len(query_set & artist_words) / max(len(artist_words), len(query_set))
        if artist_overlap >= 0.4:
            artist_bonus = 0.4 * artist_overlap
    if query_words and query_words[0] in artist_lower:
        artist_bonus = max(artist_bonus, 0.55)
    elif query_words and _token_set_sim(query_words[0], artist_lower) >= 0.85:
        artist_bonus = max(artist_bonus, 0.5)

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

    lead_bonus = _leading_artist_title_bonus(query_words, artist_lower, title_lower, parsed)
    title_exact = _title_exact_bonus(query_words, title_lower)
    hint_exact = _title_hint_exact_bonus(parsed, artist_lower, title_lower)

    base = (
        word_score + artist_bonus + position_bonus + fuzz_bonus + brevity_bonus
        + provider_bonus + translit_bonus + lead_bonus + title_exact + hint_exact
    )

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
    base *= _missing_title_words_penalty(query_words, title_lower, artist_lower, parsed)

    # Lyric-style queries: reward when title contains most query/title-hint words.
    title_cov = query_word_coverage(query_norm, artist, title, title_only=True)
    if len(_meaningful) >= 2 and title_cov >= 0.85:
        base += min(0.55, 0.25 + title_cov * 0.35)
    elif len(_meaningful) >= 2 and title_cov < 0.45:
        base *= 0.55

    base += _title_rare_word_bonus(query_norm, title_lower)
    base += _title_keyword_from_query_bonus(query_norm, title_lower)
    base += _fragment_title_stem_bonus(query_norm, title_lower)

    # Lyric fragment with weak title overlap → likely wrong song (not the lyric line).
    if is_lyric_like_query(query_norm, parsed) and title_cov < 0.35 and len(_meaningful) >= 3:
        base *= 0.45

    # Artist-only query: boost best artist match (леонид портной / typo партной).
    if parsed and parsed.get("artist_hint") and not parsed.get("title_hint"):
        a_sim = _artist_tokens_match(parsed["artist_hint"], artist_lower)
        if a_sim >= 0.65:
            base += min(0.95, 0.4 + a_sim * 0.55)

    # Explicit "artist + title" bonus (incl. typo title hints via coverage).
    if parsed and parsed.get("artist_hint") and parsed.get("title_hint"):
        a_sim = _artist_tokens_match(parsed["artist_hint"], artist_lower)
        t_cov = query_title_hint_coverage(query_norm, title, parsed)
        if a_sim >= 0.5 and t_cov >= 0.5:
            base += 0.35 + 0.45 * ((a_sim + t_cov) / 2)
        elif t_cov >= 0.85:
            base += 0.4

    base *= _lyric_distinctive_miss_penalty(query_norm, title_lower, parsed)
    base *= _false_artist_fragment_penalty(query_norm, artist_lower, title_lower)
    base *= _parsed_artist_mismatch_penalty(parsed, artist_lower, title_lower)

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
                rf_sim = float(_rf_fuzz.token_sort_ratio(key, existing_key)) / 100.0
                jac_sim = _jaccard_similarity(key, existing_key)
                sim = min(rf_sim, jac_sim)
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
                    (t.get("_score_query") or query_norm),
                    t.get("uploader", ""),
                    t.get("title", ""),
                    position=t.get("_provider_pos", 5),
                    parsed=None if t.get("_from_lyrics") or t.get("_from_lyric_fallback") else parsed,
                )
                + float(t.get("_hint_bonus", 0.0))
                # Popularity boost: cached tracks get bonus proportional to download count
                + (min(0.30, 0.05 + t.get("_downloads", 0) / 200) if t.get("file_id") else 0.0)
                # Downloadability bonus: YouTube is fragile (bot detection, LOGIN_REQUIRED),
                # so any other source with a reasonable match should win the top slot.
                + (0.0 if t.get("source", "") == "youtube" else 0.35)
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
