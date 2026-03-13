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
import aiohttp
from datetime import datetime, timezone
from pathlib import Path

from bot.config import settings
from bot.services.cache import cache
from bot.services.downloader import cleanup_staged_files, finalize_staged_file, stage_path_for

logger = logging.getLogger(__name__)

_PROACTIVE_REFRESH_SECONDS = 3600
_ADMIN_ALERT_THROTTLE_SECONDS = 900
_ADMIN_ALERT_THROTTLE_KEY = "alert:yandex_token_refresh_fail:throttle"


def _parse_expiry(raw: str | None) -> int | None:
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        if value.isdigit():
            return int(value)
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None

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


def _load_token_expiries(tokens: list[str]) -> dict[str, int]:
    expiries: dict[str, int] = {}

    pool_raw = getattr(settings, "YANDEX_TOKENS_EXPIRES_AT", None) or ""
    pool_exp = [x.strip() for x in pool_raw.split(",")] if pool_raw else []
    for idx, token in enumerate(tokens):
        if idx < len(pool_exp):
            ts = _parse_expiry(pool_exp[idx])
            if ts:
                expiries[token] = ts

    single = (settings.YANDEX_MUSIC_TOKEN or "").strip()
    single_exp = _parse_expiry(getattr(settings, "YANDEX_TOKEN_EXPIRES_AT", None))
    if single and single_exp:
        expiries[single] = single_exp

    return expiries


_tokens = _load_tokens()
_token_cycle = itertools.cycle(_tokens) if _tokens else None
_token_expiries = _load_token_expiries(_tokens)
_token_lock = asyncio.Lock()


def _token_expires_at(token: str) -> int | None:
    return _token_expiries.get(token)


def _is_token_expiring_soon(token: str, *, now_ts: int | None = None) -> bool:
    expires_at = _token_expires_at(token)
    if not expires_at:
        return False
    if now_ts is None:
        now_ts = int(datetime.now(timezone.utc).timestamp())
    return expires_at - now_ts <= _PROACTIVE_REFRESH_SECONDS


async def _admin_alert(text: str) -> None:
    should_send = True
    try:
        throttle_ok = await cache.redis.set(
            _ADMIN_ALERT_THROTTLE_KEY,
            "1",
            ex=_ADMIN_ALERT_THROTTLE_SECONDS,
            nx=True,
        )
        should_send = bool(throttle_ok)
        await cache.redis.setex("alert:yandex_token_refresh_fail", _ADMIN_ALERT_THROTTLE_SECONDS, text)
    except Exception:
        pass

    if should_send:
        await _send_admin_telegram_alert(text)

    logger.error(text)


async def _send_admin_telegram_alert(text: str) -> None:
    if not getattr(settings, "YANDEX_ALERT_TELEGRAM", True):
        return
    if not settings.BOT_TOKEN or not settings.ADMIN_IDS:
        return

    url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage"
    msg = f"⚠️ Yandex token alert\n\n{text}"

    try:
        timeout = aiohttp.ClientTimeout(total=4)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for admin_id in settings.ADMIN_IDS:
                try:
                    await session.post(
                        url,
                        json={
                            "chat_id": int(admin_id),
                            "text": msg,
                        },
                    )
                except Exception:
                    continue
    except Exception:
        return


async def _refresh_token_if_needed(token: str) -> str | None:
    """Return a usable token.

    If current token expires in <= 1 hour, rotate to another token that is not
    expiring soon. If no such token exists, raise admin alert and return None.
    """
    if not _is_token_expiring_soon(token):
        return token

    # Drop cached client proactively so stale auth state is not reused.
    _clients.pop(token, None)

    for candidate in _tokens:
        if candidate != token and not _is_token_expiring_soon(candidate):
            return candidate

    await _admin_alert("Yandex token refresh failed: all configured tokens expire within 1 hour")
    return None


async def _next_token() -> str | None:
    if _token_cycle is None:
        return None
    async with _token_lock:
        return next(_token_cycle)


# ── Client cache (one per token to avoid repeated init) ──────────────────
_clients: dict[str, object] = {}


async def _get_client(token: str):
    if token in _clients:
        return _clients[token]
    try:
        from yandex_music import ClientAsync

        # Pass proxy from pool if available
        proxy = _get_proxy_url()
        kwargs: dict = {}
        if proxy:
            kwargs["proxy_url"] = proxy
        client = await ClientAsync(token, **kwargs).init()
        _clients[token] = client
        return client
    except Exception as e:
        logger.error("Yandex client init failed: %s", e)
        return None


def _get_proxy_url() -> str | None:
    """Get next proxy URL from pool for Yandex HTTP requests."""
    try:
        from bot.services.proxy_pool import proxy_pool
        return proxy_pool.get_next()
    except Exception:
        return None


# _fmt_dur removed — yandex uses inline formatting in _track_to_dict


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
        
        # Extract cover URL from track's og_image or album cover
        cover_url = None
        try:
            if hasattr(track, "og_image") and track.og_image:
                cover_url = "https://" + track.og_image.replace("%%", "400x400")
            elif hasattr(track, "cover_uri") and track.cover_uri:
                cover_url = "https://" + track.cover_uri.replace("%%", "400x400")
            elif hasattr(track, "albums") and track.albums:
                album = track.albums[0]
                if hasattr(album, "cover_uri") and album.cover_uri:
                    cover_url = "https://" + album.cover_uri.replace("%%", "400x400")
        except Exception:
            pass
        
        return {
            "video_id": track_id,
            "ym_track_id": int(track.id),
            "title": title,
            "uploader": artist,
            "duration": s,
            "duration_fmt": f"{m}:{sec:02d}",
            "source": "yandex",
            "cover_url": cover_url,
        }
    except Exception:
        return None


# ── Public API ────────────────────────────────────────────────────────────

async def search_yandex(query: str, limit: int = 5) -> list[dict]:
    """Search Yandex Music. Returns [] on any failure."""
    token = await _next_token()
    if not token:
        return []
    token = await _refresh_token_if_needed(token)
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
                # Attach the token used for this search so download can reuse it
                d["_ym_token"] = token
                tracks.append(d)
            if len(tracks) >= limit:
                break
        return tracks
    except Exception as e:
        logger.error("Yandex search error: %s", e)
        # Invalidate cached client so next call re-inits with next token
        _clients.pop(token, None)
        return []


async def download_yandex(track_id: int, dest: Path, bitrate: int = 320, token: str | None = None) -> Path:
    """Download a Yandex Music track by numeric ID to dest (MP3).

    If ``token`` is provided, reuse it to keep search+download on the same token.
    """
    if token is None:
        token = await _next_token()
    if not token:
        raise RuntimeError("No Yandex token configured")
    token = await _refresh_token_if_needed(token)
    if not token:
        raise RuntimeError("No valid Yandex token available")
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

    staged_dest = stage_path_for(dest, suffix=".yandex")
    try:
        await chosen.download_async(str(staged_dest))
    except Exception:
        cleanup_staged_files(staged_dest)
        raise
    if not staged_dest.exists() or staged_dest.stat().st_size < 1024:
        cleanup_staged_files(staged_dest)
        raise RuntimeError(f"Downloaded file too small or missing: {dest}")
    return finalize_staged_file(staged_dest, dest)


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

    token = await _next_token()
    if not token:
        logger.warning("resolve_yandex_url: no Yandex token configured")
        return None
    token = await _refresh_token_if_needed(token)
    if not token:
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


async def fetch_yandex_track(track_id: int) -> dict | None:
    """Fetch Yandex Music track metadata by numeric track ID."""
    token = await _next_token()
    if not token:
        logger.warning("fetch_yandex_track: no Yandex token configured")
        return None
    token = await _refresh_token_if_needed(token)
    if not token:
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
        logger.error("fetch_yandex_track error for track %s: %s", track_id, e)
        _clients.pop(token, None)
        return None
