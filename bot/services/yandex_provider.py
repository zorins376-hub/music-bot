"""Яндекс.Музыка — поиск и скачивание треков.

Конфиг:
    YANDEX_MUSIC_TOKEN  — один токен
    YANDEX_TOKENS       — несколько через запятую (round-robin ротация)

Если токен не задан — возвращает [] без ошибок.
Если yandex-music не установлен — возвращает [] без ошибок.
"""
import asyncio
import itertools
import logging
import re
import tempfile
from pathlib import Path

from bot.config import settings

logger = logging.getLogger(__name__)

# ── Token pool (round-robin) ──────────────────────────────────────────────

def _load_tokens() -> list[str]:
    tokens: list[str] = []
    # YANDEX_TOKENS=tok1,tok2,tok3 (pool)
    pool_raw = getattr(settings, "YANDEX_TOKENS", None) or ""
    for t in pool_raw.split(","):
        t = t.strip()
        if t:
            tokens.append(t)
    # YANDEX_MUSIC_TOKEN (single fallback)
    single = settings.YANDEX_MUSIC_TOKEN or ""
    if single.strip() and single.strip() not in tokens:
        tokens.append(single.strip())
    return tokens


_tokens = _load_tokens()
_token_cycle = itertools.cycle(_tokens) if _tokens else None


def _next_token() -> str | None:
    if _token_cycle is None:
        return None
    return next(_token_cycle)


# ── Client cache (one per token to avoid repeated init) ──────────────────
_clients: dict[str, object] = {}


async def _get_client(token: str):
    if token in _clients:
        return _clients[token]
    try:
        from yandex_music import ClientAsync
        client = await ClientAsync(token).init()
        _clients[token] = client
        return client
    except Exception as e:
        logger.error("Yandex client init failed: %s", e)
        return None


def _fmt_dur(ms: int) -> str:
    s = ms // 1000
    m, sec = divmod(s, 60)
    return f"{m}:{sec:02d}"


def _track_to_dict(track, source_id: str | None = None) -> dict | None:
    """Convert yandex_music Track object to our internal dict."""
    try:
        title: str = (track.title or "").strip()
        artists = track.artists or []
        artist: str = ", ".join(a.name for a in artists if a.name).strip()
        if not title or not artist:
            return None
        dur_ms: int = track.duration_ms or 0
        if dur_ms and dur_ms > settings.MAX_DURATION * 1000:
            return None
        track_id = source_id or (
            f"ym_{track.id}" if hasattr(track, "id") and track.id else None
        )
        if not track_id:
            return None
        s = dur_ms // 1000
        m, sec = divmod(s, 60)
        return {
            "video_id": track_id,
            "ym_track_id": int(track.id),
            "title": title,
            "uploader": artist,
            "duration": s,
            "duration_fmt": f"{m}:{sec:02d}",
            "source": "yandex",
        }
    except Exception:
        return None


# ── Public API ────────────────────────────────────────────────────────────

async def search_yandex(query: str, limit: int = 5) -> list[dict]:
    """Search Yandex Music. Returns [] on any failure."""
    token = _next_token()
    if not token:
        return []
    try:
        from yandex_music import ClientAsync  # noqa: F401
    except ImportError:
        logger.warning("yandex-music not installed")
        return []

    try:
        client = await _get_client(token)
        if client is None:
            return []
        result = await client.search(query, type_="track", page=0)
        if not result or not result.tracks:
            return []
        tracks = []
        for tr in result.tracks.results:
            d = _track_to_dict(tr)
            if d:
                tracks.append(d)
            if len(tracks) >= limit:
                break
        return tracks
    except Exception as e:
        logger.error("Yandex search error: %s", e)
        # Invalidate cached client so next call re-inits with next token
        _clients.pop(token, None)
        return []


async def download_yandex(track_id: int, dest: Path, bitrate: int = 320) -> Path:
    """Download a Yandex Music track by numeric ID to dest (MP3)."""
    token = _next_token()
    if not token:
        raise RuntimeError("No Yandex token configured")
    try:
        from yandex_music import ClientAsync  # noqa: F401
    except ImportError:
        raise RuntimeError("yandex-music not installed")

    client = await _get_client(token)
    if client is None:
        raise RuntimeError("Yandex client unavailable")

    # Fetch full track info
    tracks_list = await client.tracks([track_id])
    if not tracks_list:
        raise RuntimeError(f"Track {track_id} not found on Yandex Music")
    track = tracks_list[0]

    # Find best download info (prefer MP3 at requested bitrate)
    download_infos = await track.get_download_info_async()
    if not download_infos:
        raise RuntimeError(f"No download info for track {track_id}")

    # Sort: mp3 first, then by bitrate descending
    mp3_infos = [d for d in download_infos if d.codec == "mp3"]
    other_infos = [d for d in download_infos if d.codec != "mp3"]
    sorted_infos = sorted(mp3_infos, key=lambda d: d.bitrate_in_kbps, reverse=True) + other_infos

    # Pick closest bitrate without exceeding requested
    chosen = sorted_infos[0]
    for di in sorted_infos:
        if di.codec == "mp3" and di.bitrate_in_kbps <= bitrate:
            chosen = di
            break

    await chosen.download_async(str(dest))
    if not dest.exists() or dest.stat().st_size < 1024:
        raise RuntimeError(f"Downloaded file too small or missing: {dest}")
    return dest


# ── Yandex Music link resolver ───────────────────────────────────────────

_YANDEX_TRACK_RE = re.compile(
    r"https?://music\.yandex\.(?:ru|com|kz|by|uz)/album/\d+/track/(\d+)"
)


def is_yandex_music_url(text: str) -> bool:
    return bool(_YANDEX_TRACK_RE.search(text))


async def resolve_yandex_url(url: str) -> dict | None:
    """Resolve a Yandex Music track URL to an internal track dict.

    Returns a dict compatible with search results (video_id, ym_track_id,
    title, uploader, duration, source='yandex') or None on failure.
    """
    m = _YANDEX_TRACK_RE.search(url)
    if not m:
        return None
    track_id = int(m.group(1))

    token = _next_token()
    if not token:
        logger.warning("resolve_yandex_url: no Yandex token configured")
        return None
    try:
        from yandex_music import ClientAsync  # noqa: F401
    except ImportError:
        return None

    try:
        client = await _get_client(token)
        if client is None:
            return None
        tracks = await client.tracks([track_id])
        if not tracks:
            return None
        return _track_to_dict(tracks[0], source_id=f"ym_{track_id}")
    except Exception as e:
        logger.error("resolve_yandex_url error for track %s: %s", track_id, e)
        _clients.pop(token, None)
        return None
