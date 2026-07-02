"""Clean artist/title metadata for Telegram audio display."""
from __future__ import annotations

import re

try:
    from rapidfuzz import fuzz as _rf_fuzz
except Exception:
    _rf_fuzz = None

_TELEGRAM_TAG_LIMIT = 64

_TITLE_JUNK_RE = re.compile(
    r"\s*[\(\[]"
    r"(?:official\s*(?:music\s*)?video|official\s*audio|official\s*lyric[s]?\s*video"
    r"|lyric[s]?\s*video|lyric[s]?|audio|music\s*video|видеоклип|клип|текст"
    r"|hd|hq|4k|1080p|720p|mv|m/v"
    r"|remaster(?:ed)?(?:\s*\d{4})?"
    r"|live(?:\s+(?:at|from|in)\s+[^)\]]+)?"
    r"|explicit|clean|censored|deluxe(?:\s*edition)?"
    r"|bonus\s*track|acoustic(?:\s*version)?"
    r"|animated\s*video|visualizer"
    r"|slowed\+?reverb|slowed|reverb|sped\s*up|speed\s*up|nightcore"
    r"|prod\.?\s*(?:by\s*)?[^)\]]*"
    r"|премьера\s*(?:клипа)?\s*,?\s*\d{4}|премьера\s*\d{4}"
    r"|ft\.?[^)\]]*|feat\.?[^)\]]*)\s*[\)\]]",
    re.IGNORECASE,
)
_EXTRA_JUNK_RE = re.compile(
    r"\s*\|.*$"
    r"|\s*//.*$"
    r"|\s*#\w+"
    r"|\s*-\s*(?:YouTube|Topic|Тема)\s*$"
    r"|\s*\(\s*\)"
    r"|\s*\[\s*\]",
    re.IGNORECASE,
)
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001F9FF\U00002700-\U000027BF\U0000FE00-\U0000FE0F"
    "\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U00002600-\U000026FF]+",
)
_LIVE_DATE_RE = re.compile(
    r"\s*[\(\[]\d{1,2}\.\d{1,2}\.\d{4}[^\)\]]*[\)\]]",
)
_CLIP_SUFFIX_RE = re.compile(
    r"\s*/\s*(?:жаны\s*)?клип.*$"
    r"|\s*/\s*[^/]*(?:клип|clip)\s*$",
    re.IGNORECASE,
)
_FILE_EXT_RE = re.compile(r"\.(?:mp3|wav|flac|m4a|ogg|aac)\s*$", re.IGNORECASE)
_SITE_TAG_RE = re.compile(
    r"\s*[\[\(](?:muzvat\.com|audio\s*library|provided\s*to\s*youtube)[^\)\]]*[\)\]]",
    re.IGNORECASE,
)
_TRAILING_JUNK_WORDS_RE = re.compile(
    r"\s+(?:lyrics|audio|video|текст|official)\s*$",
    re.IGNORECASE,
)


def clean_title(raw_title: str) -> str:
    """Strip junk from a track title for display."""
    cleaned = raw_title or ""
    cleaned = _TITLE_JUNK_RE.sub("", cleaned)
    cleaned = _LIVE_DATE_RE.sub("", cleaned)
    cleaned = _SITE_TAG_RE.sub("", cleaned)
    cleaned = _CLIP_SUFFIX_RE.sub("", cleaned)
    cleaned = _EXTRA_JUNK_RE.sub("", cleaned)
    cleaned = _EMOJI_RE.sub("", cleaned)
    cleaned = _FILE_EXT_RE.sub("", cleaned)
    cleaned = _TRAILING_JUNK_WORDS_RE.sub("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def clean_artist(raw_artist: str) -> str:
    """Strip channel/topic junk from artist name."""
    artist = (raw_artist or "").strip()
    for suffix in (" - Topic", " - Тема"):
        if artist.endswith(suffix):
            artist = artist[: -len(suffix)].strip()
    if artist.upper().endswith("VEVO"):
        artist = artist[:-4].strip()
    artist = re.sub(r"\s*Official\s*(?:Channel|Artist)?\s*$", "", artist, flags=re.IGNORECASE)
    artist = _EMOJI_RE.sub("", artist)
    artist = re.sub(r"\s{2,}", " ", artist)
    return artist.strip()


def _names_match(a: str, b: str) -> bool:
    a_norm = a.lower().strip()
    b_norm = b.lower().strip()
    if not a_norm or not b_norm:
        return False
    if a_norm == b_norm or a_norm in b_norm or b_norm in a_norm:
        return True
    if _rf_fuzz is not None:
        return float(_rf_fuzz.token_set_ratio(a_norm, b_norm)) >= 88
    return False


def _clip_tag(text: str, limit: int = _TELEGRAM_TAG_LIMIT) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def format_track_display(artist: str, title: str) -> tuple[str, str]:
    """Return clean (performer, title) for Telegram audio tags."""
    artist = clean_artist(artist)
    title = clean_title(title)

    # Title embeds "Artist - Song" while performer is set separately.
    for sep in (" — ", " – ", " - "):
        if sep in title:
            head, tail = title.split(sep, 1)
            head, tail = head.strip(), tail.strip()
            if head and tail and _names_match(head, artist):
                title = tail
                break

    # Drop duplicated artist prefix: "MACAN — MACAN L" -> "L"
    al, tl = artist.lower(), title.lower()
    for sep in (" — ", " – ", " - ", ": "):
        prefix = artist + sep.strip()
        if title.startswith(prefix):
            title = title[len(prefix):].strip()
            break
        if tl.startswith(al + sep.strip().lower()):
            title = title[len(artist) + len(sep):].strip()
            break

    if not artist:
        artist = "Unknown"
    if not title:
        title = "Untitled"

    return _clip_tag(artist), _clip_tag(title)


def audio_tag_kwargs_from_info(info: dict) -> dict[str, str]:
    """Telegram answer_audio kwargs with cleaned performer/title."""
    performer, title = format_track_display(
        info.get("uploader") or info.get("artist") or "",
        info.get("title") or "",
    )
    return {"performer": performer, "title": title}


def audio_tag_kwargs(artist: str, title: str) -> dict[str, str]:
    """Telegram answer_audio kwargs from raw artist/title."""
    performer, clean_title = format_track_display(artist, title)
    return {"performer": performer, "title": clean_title}


def format_track_line(artist: str, title: str) -> str:
    """Human-readable 'Artist — Title' line."""
    a, t = format_track_display(artist, title)
    return f"{a} — {t}"


def parse_artist_title(raw_title: str, uploader: str) -> tuple[str, str]:
    """Extract clean (artist, title) from a raw video title + uploader."""
    cleaned = clean_title(raw_title)

    for sep in (" — ", " – ", " - "):
        if sep in cleaned:
            parts = cleaned.split(sep, 1)
            a, t = parts[0].strip(), parts[1].strip()
            if a and t:
                return format_track_display(a, t)

    return format_track_display(uploader or "Unknown", cleaned or raw_title)
