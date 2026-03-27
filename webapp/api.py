"""
TMA Player — FastAPI backend for Telegram Mini App.

Endpoints:
  GET  /api/player/state/{user_id}  — current player state
  POST /api/player/action           — play/pause/next/prev/seek/shuffle/repeat
  GET  /api/playlists/{user_id}     — user playlists
  GET  /api/playlist/{id}/tracks    — playlist tracks
  GET  /api/lyrics/{track_id}       — lyrics for a track
  GET  /api/search?q=...            — search tracks
"""
import asyncio
import json
import logging
import os
import traceback
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlparse

# Initialize structlog
os.environ.setdefault("STRUCTLOG_LAZY_INIT", "1")
from bot.logging_config import configure_logging, get_logger
configure_logging()

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from bot.config import settings
from bot.services.downloader import download_track, resolve_youtube_audio_stream_url
from bot.services.download_manager import download_manager
from bot.models.base import init_db


def _is_valid_mp3(path: Path) -> bool:
    """Lightweight MP3 sanity check: header magic + minimum size."""
    try:
        if not path.exists():
            return False
        if path.stat().st_size < 16 * 1024:  # too small to be a full track
            return False
        head = path.read_bytes()[:3]
        return head in (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")
    except OSError:
        return False


def _yt_thumb(video_id: str) -> str | None:
    """Return YouTube thumbnail URL if video_id looks like a YouTube ID."""
    if not video_id or video_id.startswith(("ym_", "sp_", "dz_", "vk_", "sc_", "am_")):
        return None
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def _select_bitrate(pref: str | None, premium: bool) -> int:
    """Map stored quality preference to bitrate for yt-dlp pipeline.

    When CACHE_CHANNEL_ID is set, always download at 320kbps
    so cached files are max quality for all users.
    """
    if settings.CACHE_CHANNEL_ID:
        return 320
    if pref == "auto" or not pref:
        return settings.DEFAULT_BITRATE
    if pref == "320" and premium:
        return 320
    if pref in {"128", "192", "320"}:
        return int(pref)
    return settings.DEFAULT_BITRATE


# Strong references to background tasks to prevent GC before completion
_background_tasks: set[asyncio.Task] = set()


def _fire_task(coro) -> asyncio.Task:
    """Create a background task with GC protection."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)

    def _on_done(done: asyncio.Task) -> None:
        _background_tasks.discard(done)
        if done.cancelled():
            return
        exc = done.exception()
        if exc is not None:
            logger.exception("Background task failed", exc_info=exc)

    task.add_done_callback(_on_done)
    return task


def _schedule_background_download(video_id: str, bitrate: int) -> None:
    """Fire-and-forget mp3 download so next play hits cache."""
    async def _run():
        try:
            await download_manager.download(video_id, bitrate=bitrate)
        except Exception:
            logger.warning("Background download failed for %s", video_id)

    _fire_task(_run())

# ── Bounded LRU dict (evicts oldest when maxsize exceeded) ────────────────
class _BoundedDict(dict):
    """Dict with maxsize — removes oldest entries when limit is reached."""
    def __init__(self, maxsize: int = 5000):
        super().__init__()
        self._maxsize = maxsize
    def __setitem__(self, key, value):
        if len(self) >= self._maxsize and key not in self:
            # Remove oldest 10%
            to_remove = max(1, self._maxsize // 10)
            for k in list(self.keys())[:to_remove]:
                dict.__delitem__(self, k)
        super().__setitem__(key, value)

# ── In-memory stream URL cache (avoids repeated yt-dlp resolves) ─────────
_stream_url_cache: dict[str, tuple[str, float]] = _BoundedDict(5000)
_STREAM_URL_TTL = 10800  # 3 hours (YouTube URLs valid ~6h)
_stream_url_inflight: dict[str, asyncio.Future[str | None]] = {}
_stream_url_lock = asyncio.Lock()
_stream_url_resolve_semaphore = asyncio.Semaphore(6)

# ── Download coalescing for non-YouTube tracks (ym_, sp_) ─────────────────
_dl_inflight: dict[str, asyncio.Future[Path]] = {}
_dl_inflight_lock = asyncio.Lock()
_cover_url_cache: dict[str, tuple[str | None, float]] = _BoundedDict(2000)
_COVER_URL_TTL = 3600
_user_audio_cache: dict[int, tuple[str, bool, float]] = _BoundedDict(5000)
_USER_AUDIO_CACHE_TTL = 60
_LYRICS_CACHE_TTL = 86400 * 7
_LYRICS_MISS_TTL = 86400  # 24h — tracks without lyrics rarely gain them
_LYRICS_CACHE_MISS = "__MISS__"
from webapp.auth import verify_init_data
from webapp.schemas import (
    LyricsResponse,
    PartyAddTrackRequest,
    PartyChatRequest,
    PartyChatMessageSchema,
    PartyCreateRequest,
    PartyEventSchema,
    PartyMemberSchema,
    PartyPlaybackRequest,
    PartyPlaybackStateSchema,
    PartyReactionRequest,
    PartyRecapSchema,
    PartyRecapStatSchema,
    PartyReorderRequest,
    PartyRoleUpdateRequest,
    PartySchema,
    PartyTrackSchema,
    PlayerAction,
    PlayerState,
    PlaylistSchema,
    SearchResult,
    TrackSchema,
    UserAudioSettingsSchema,
    UserProfileSchema,
)

# ── Error file logger ────────────────────────────────────────────────────
_LOG_DIR = Path("/app/logs") if Path("/app").exists() else Path("logs")
_LOG_DIR.mkdir(parents=True, exist_ok=True)

_error_handler = RotatingFileHandler(
    _LOG_DIR / "errors.log", maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
_error_handler.setLevel(logging.ERROR)
_error_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
))
logging.getLogger().addHandler(_error_handler)

logger = get_logger(__name__)


def _normalize_origin(value: str) -> str | None:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _build_allowed_origins() -> list[str]:
    origins: set[str] = set()

    for item in getattr(settings, "WEBAPP_CORS_ORIGINS", []) or []:
        normalized = _normalize_origin(item)
        if normalized:
            origins.add(normalized)

    tma_url = getattr(settings, "TMA_URL", None)
    if tma_url:
        normalized = _normalize_origin(tma_url)
        if normalized:
            origins.add(normalized)

    if os.environ.get("ENV", "").lower() in {"dev", "development", "local"}:
        origins.update({"http://localhost:5173", "http://127.0.0.1:5173"})

    return sorted(origins)


def _get_cached_user_audio(user_id: int) -> tuple[str, bool] | None:
    import time as _time

    item = _user_audio_cache.get(user_id)
    if not item:
        return None
    quality, premium, expires_at = item
    if expires_at <= _time.time():
        _user_audio_cache.pop(user_id, None)
        return None
    return quality, premium


def _set_cached_user_audio(user_id: int, quality: str, premium: bool) -> None:
    import time as _time

    _user_audio_cache[user_id] = (quality, premium, _time.time() + _USER_AUDIO_CACHE_TTL)


async def _resolve_user_audio_profile(user: dict) -> tuple[str, bool]:
    user_id = int(user["id"])
    cached = _get_cached_user_audio(user_id)
    if cached is not None:
        return cached

    db_user = await _get_or_create_webapp_user(user)
    quality = str(db_user.quality or "192")
    premium = bool(db_user.is_premium or db_user.is_admin)
    _set_cached_user_audio(user_id, quality, premium)
    return quality, premium


# ── Auth dependency ──────────────────────────────────────────────────────

async def get_current_user(x_telegram_init_data: str = Header(...)) -> dict:
    """Extract and verify Telegram user from initData header."""
    user = verify_init_data(x_telegram_init_data)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid initData")
    return user


# ── Lifespan ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    # Chart cache prewarm (same as bot, ensures webapp has fresh charts)
    from bot.handlers.charts import _prewarm_charts_once
    _fire_task(_prewarm_charts_once())

    # Background track indexer is started in bot/main.py — no need to duplicate here

    # Periodic cleanup of expired stream URL cache entries
    async def _cleanup_url_cache():
        import time as _time
        while True:
            await asyncio.sleep(300)  # every 5 min
            now = _time.time()
            expired = [k for k, (_, exp) in _stream_url_cache.items() if exp < now]
            for k in expired:
                _stream_url_cache.pop(k, None)
            expired_covers = [k for k, (_, exp) in _cover_url_cache.items() if exp < now]
            for k in expired_covers:
                _cover_url_cache.pop(k, None)
            if expired:
                logger.debug("Cleaned %d expired stream URL cache entries", len(expired))
            if expired_covers:
                logger.debug("Cleaned %d expired cover cache entries", len(expired_covers))

    # Periodic cleanup of stale .part downloads (every 30 min)
    async def _cleanup_stale_downloads():
        import time as _time
        dl_dir = settings.DOWNLOAD_DIR
        while True:
            await asyncio.sleep(1800)  # every 30 min
            try:
                now = _time.time()
                for p in dl_dir.glob("*.part"):
                    try:
                        if now - p.stat().st_mtime > 3600:  # older than 1h
                            p.unlink(missing_ok=True)
                    except OSError:
                        pass
            except Exception:
                logger.debug("stale download cleanup error", exc_info=True)

    cleanup_task = _fire_task(_cleanup_url_cache())
    dl_cleanup_task = _fire_task(_cleanup_stale_downloads())
    yield
    cleanup_task.cancel()
    dl_cleanup_task.cancel()
    await download_manager.shutdown()


# ── App ──────────────────────────────────────────────────────────────────

app = FastAPI(title="TMA Player", version="1.0.0", lifespan=lifespan)

_allowed_origins = _build_allowed_origins()
if not _allowed_origins:
    logger.warning("CORS allow list is empty; cross-origin access is disabled")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Admin Panel API ─────────────────────────────────────────────────────
from webapp.admin_api import router as admin_router
app.include_router(admin_router)


# ── Global exception handler ────────────────────────────────────────────

@app.middleware("http")
async def catch_exceptions_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except asyncio.CancelledError:
        # Client disconnected — don't log as error, just return 499
        logger.debug("Request cancelled: %s %s", request.method, request.url.path)
        return JSONResponse(status_code=499, content={"detail": "Client closed request"})
    except Exception as exc:
        logger.error(
            "Unhandled %s %s → %s\n%s",
            request.method,
            request.url.path,
            exc,
            traceback.format_exc(),
        )
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data: https: blob:; "
        "media-src 'self' https: blob:; "
        "connect-src 'self' https: wss:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "frame-ancestors 'self' https://*.telegram.org https://t.me;"
    )
    return response


# ── Simple in-memory rate limiter ──────────────────────────────────────

import time as _time_module

class _RateLimiter:
    """Token-bucket rate limiter per user_id."""
    __slots__ = ("_buckets", "_rate", "_burst", "_maxusers")
    def __init__(self, rate: float = 2.0, burst: int = 10, maxusers: int = 10000):
        self._buckets: dict[int, list[float]] = {}  # uid -> [tokens, last_ts]
        self._rate = rate     # tokens per second
        self._burst = burst   # max tokens
        self._maxusers = maxusers
    def allow(self, uid: int) -> bool:
        now = _time_module.monotonic()
        if uid not in self._buckets:
            if len(self._buckets) >= self._maxusers:
                oldest = min(self._buckets, key=lambda k: self._buckets[k][1])
                del self._buckets[oldest]
            self._buckets[uid] = [float(self._burst - 1), now]
            return True
        tokens, last = self._buckets[uid]
        tokens = min(self._burst, tokens + (now - last) * self._rate)
        self._buckets[uid] = [tokens - 1, now]
        return tokens >= 1

_action_limiter = _RateLimiter(rate=3.0, burst=15)  # player actions
_search_limiter = _RateLimiter(rate=1.5, burst=8)    # search
_stream_limiter = _RateLimiter(rate=4.0, burst=15)    # stream downloads

@app.get("/health")
async def health():
    """Liveness probe — process is alive."""
    return {"status": "ok", "uptime_s": int(_time_module.monotonic())}


@app.get("/readyz")
async def readiness():
    """Readiness probe — all dependencies are available."""
    import os
    checks: dict[str, str] = {}

    # Check PostgreSQL
    try:
        from sqlalchemy import text
        from bot.models.base import async_session
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as e:
        checks["db"] = f"error: {e}"

    # Check Redis
    try:
        from bot.services.cache import cache
        await cache.redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    # Memory usage (cross-platform)
    try:
        import psutil
        mem_mb = round(psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024, 1)
    except ImportError:
        mem_mb = None

    all_ok = all(v == "ok" for v in checks.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "checks": checks,
        "stream_cache_size": len(_stream_url_cache),
        "cover_cache_size": len(_cover_url_cache),
        "mem_mb": mem_mb,
    }


async def _get_or_create_webapp_user(tg_user: dict):
    from bot.db import get_or_create_user_raw

    user_id = int(tg_user["id"])
    username = tg_user.get("username")
    first_name = tg_user.get("first_name") or ""
    return await get_or_create_user_raw(user_id, username, first_name)


@app.get("/api/user/me", response_model=UserProfileSchema)
async def get_me(user: dict = Depends(get_current_user)):
    db_user = await _get_or_create_webapp_user(user)
    return UserProfileSchema(
        id=db_user.id,
        first_name=db_user.first_name or "",
        username=db_user.username,
        is_premium=bool(db_user.is_premium),
        is_admin=bool(db_user.is_admin),
        quality=str(db_user.quality or "192"),
    )



@app.post("/api/user/audio-settings", response_model=UserProfileSchema)
async def update_audio_settings(body: UserAudioSettingsSchema, user: dict = Depends(get_current_user)):
    from sqlalchemy import update

    from bot.models.base import async_session
    from bot.models.user import User

    db_user = await _get_or_create_webapp_user(user)
    quality = str(body.quality)
    if quality not in {"auto", "128", "192", "320"}:
        raise HTTPException(status_code=400, detail="Invalid quality")
    if quality == "320" and not (db_user.is_premium or db_user.is_admin):
        raise HTTPException(status_code=403, detail="Premium only")

    async with async_session() as session:
        await session.execute(update(User).where(User.id == db_user.id).values(quality=quality))
        await session.commit()

    db_user.quality = quality
    _set_cached_user_audio(db_user.id, quality, bool(db_user.is_premium or db_user.is_admin))
    return UserProfileSchema(
        id=db_user.id,
        first_name=db_user.first_name or "",
        username=db_user.username,
        is_premium=bool(db_user.is_premium),
        is_admin=bool(db_user.is_admin),
        quality=quality,
    )


@app.get("/api/errors")
async def view_errors(
    lines: int = Query(200, ge=1, le=5000),
    user: dict = Depends(get_current_user),
):
    """Return last N lines from errors.log (admin only)."""
    from bot.db import is_admin

    user_id = int(user.get("id", 0))
    username = user.get("username")
    if not is_admin(user_id, username):
        raise HTTPException(status_code=403, detail="Admin access required")

    err_file = _LOG_DIR / "errors.log"
    if not err_file.exists():
        return {"errors": []}
    text = err_file.read_text(encoding="utf-8", errors="replace")
    all_lines = text.strip().splitlines()
    return {"errors": all_lines[-lines:]}


# ── Audio streaming ─────────────────────────────────────────────────────

@app.get("/api/stream/{video_id}")
async def stream_audio(
    request: Request,
    video_id: str,
    x_telegram_init_data: str | None = Header(None),
    token: str | None = Query(None),
):
    """Download (if needed) and stream MP3 for a given video_id with Range support."""
    # Auth: accept header or query param (audio elements can't send headers)
    init_data = x_telegram_init_data or token
    user = verify_init_data(init_data) if init_data else None
    if user is None:
        raise HTTPException(status_code=401, detail="Unauthorized")

    uid = int(user.get("id", 0))
    if not _stream_limiter.allow(uid):
        raise HTTPException(status_code=429, detail="Too many stream requests")

    quality, premium = await _resolve_user_audio_profile(user)
    preferred_bitrate = _select_bitrate(quality, premium)

    # Sanitize video_id to prevent path traversal
    import re
    if not re.match(r'^[a-zA-Z0-9_-]{1,64}$', video_id):
        raise HTTPException(status_code=400, detail="Invalid video_id")

    # Check if already downloaded (and has valid MP3 header)
    mp3_path = settings.DOWNLOAD_DIR / f"{video_id}.mp3"
    if mp3_path.exists():
        # Only remove truly corrupt files (very small AND invalid header)
        # Don't remove files that might be mid-stream to another request
        fsize = mp3_path.stat().st_size
        if fsize < 10 * 1024 and not _is_valid_mp3(mp3_path):
            logger.warning("Removing corrupt file %s (%d bytes)", mp3_path, fsize)
            mp3_path.unlink()

    # Telegram CDN fallback: restore from cache channel if file missing
    if not mp3_path.exists():
        try:
            from bot.services.telegram_cache import get_file_id, download_from_cache
            cached_fid = await get_file_id(video_id)
            if cached_fid:
                restored = await download_from_cache(cached_fid, mp3_path)
                if restored:
                    logger.info("Restored %s from Telegram CDN", video_id)
        except Exception:
            pass

    if not mp3_path.exists():
        try:
            # Determine source by prefix
            if video_id.startswith("ym_") or video_id.isdigit():
                # Yandex Music track — coalesce concurrent requests
                async with _dl_inflight_lock:
                    existing = _dl_inflight.get(video_id)
                    if existing is not None:
                        mp3_path = await existing
                    else:
                        future: asyncio.Future[Path] = asyncio.get_running_loop().create_future()
                        _dl_inflight[video_id] = future
                if existing is None:
                    try:
                        from bot.services.yandex_provider import download_yandex
                        track_id = int(video_id[3:]) if video_id.startswith("ym_") else int(video_id)
                        mp3_path = await download_yandex(track_id, mp3_path)
                        future.set_result(mp3_path)
                    except BaseException as exc:
                        future.set_exception(exc)
                        raise
                    finally:
                        async with _dl_inflight_lock:
                            _dl_inflight.pop(video_id, None)
            elif video_id.startswith("dz_"):
                # Deezer track — download with ARL + Blowfish decryption
                dz_id = int(video_id[3:])
                dz_quality = "MP3_320" if preferred_bitrate >= 320 else "MP3_128"
                try:
                    from bot.services.deezer_provider import download_deezer
                    result = await download_deezer(dz_id, mp3_path, quality=dz_quality)
                    if result:
                        mp3_path = result
                    else:
                        raise HTTPException(status_code=502, detail="Deezer provider unavailable")
                except Exception:
                    # Fallback: resolve metadata → search Yandex → YouTube
                    logger.info("Deezer download failed for %s, trying fallback", video_id)
                    mp3_path = await _fallback_download(video_id, "dz_", preferred_bitrate)
            elif video_id.startswith("sp_"):
                # Spotify track — fallback chain: Yandex → YouTube
                sp_query = await _spotify_id_to_query(video_id)
                if not sp_query:
                    raise HTTPException(status_code=404, detail="Spotify track not found")
                # Try Yandex first (better quality, especially for Russian music)
                mp3_path = await _try_yandex_fallback(sp_query, mp3_path)
                if not mp3_path or not mp3_path.exists():
                    # Fallback to YouTube
                    from bot.services.downloader import search_tracks
                    results = await search_tracks(sp_query, max_results=1, source="youtube")
                    if not results:
                        raise HTTPException(status_code=404, detail="No match for Spotify track")
                    yt_id = results[0].get("video_id", "")
                    if not yt_id:
                        raise HTTPException(status_code=404, detail="No match for Spotify track")
                    mp3_path = await download_manager.download(yt_id, bitrate=preferred_bitrate)
                # Hardlink so sp_ ID maps to the same file (no copy, no extra disk)
                sp_path = settings.DOWNLOAD_DIR / f"{video_id}.mp3"
                if not sp_path.exists() and mp3_path.exists():
                    try:
                        sp_path.hardlink_to(mp3_path)
                    except OSError:
                        import shutil
                        shutil.copy2(mp3_path, sp_path)
                mp3_path = sp_path
            elif video_id.startswith("am_"):
                # Apple Music — metadata-only, fallback: Yandex → YouTube
                mp3_path = await _fallback_download(video_id, "am_", preferred_bitrate)
            elif video_id.startswith("vk_"):
                # VK Music — re-search to get fresh URL, then download
                from bot.services.vk_provider import search_vk, download_vk
                vk_query = await _source_id_to_query(video_id)
                if vk_query:
                    vk_results = await search_vk(vk_query, limit=1)
                    if vk_results and vk_results[0].get("vk_url"):
                        mp3_path = await download_vk(vk_results[0]["vk_url"], mp3_path)
                    else:
                        mp3_path = await _fallback_download(video_id, "vk_", preferred_bitrate)
                else:
                    raise HTTPException(status_code=404, detail="VK track not found")
            elif not _is_likely_youtube_id(video_id):
                # Unknown source — reject early instead of sending junk to YouTube
                raise HTTPException(status_code=400, detail=f"Unsupported track source: {video_id}")
            else:
                # YouTube: try cached stream URL first, then resolve
                import time as _time
                stream_url = None
                cached = _stream_url_cache.get(video_id)
                if cached and cached[1] > _time.time():
                    stream_url = cached[0]
                    logger.debug("Stream URL cache hit for %s", video_id)
                else:
                    stream_url = await _resolve_stream_url_cached(video_id)
                if stream_url:
                    from bot.services.http_session import get_session

                    range_header = request.headers.get("range")
                    upstream_headers = {}
                    if range_header:
                        upstream_headers["Range"] = range_header

                    session = get_session()
                    upstream = await session.get(stream_url, headers=upstream_headers, allow_redirects=True)
                    if upstream.status in (200, 206):
                        async def _iter_upstream():
                            try:
                                async for chunk in upstream.content.iter_chunked(128 * 1024):
                                    yield chunk
                            finally:
                                upstream.close()

                        response_headers = {
                            "Accept-Ranges": upstream.headers.get("Accept-Ranges", "bytes"),
                            "Cache-Control": "public, max-age=3600",  # let browser cache stream chunks
                        }
                        content_length = upstream.headers.get("Content-Length")
                        content_range = upstream.headers.get("Content-Range")
                        if content_length:
                            response_headers["Content-Length"] = content_length
                        if content_range:
                            response_headers["Content-Range"] = content_range

                        if not mp3_path.exists():
                            _schedule_background_download(video_id, preferred_bitrate)

                        return StreamingResponse(
                            _iter_upstream(),
                            status_code=upstream.status,
                            media_type=upstream.headers.get("Content-Type", "audio/mpeg"),
                            headers=response_headers,
                        )
                    upstream.close()
                    # Invalidate cached stream URL on 403/404/410 (expired or geo-blocked)
                    if upstream.status in (403, 404, 410):
                        _stream_url_cache.pop(video_id, None)
                        logger.info("Evicted stale stream URL for %s (HTTP %d)", video_id, upstream.status)

                # Fallback: coalesced download via download manager
                mp3_path = await download_manager.download(video_id, bitrate=preferred_bitrate)
        except HTTPException:
            raise
        except Exception as e:
            logger.error("Stream download failed for %s: %s", video_id, e)
            raise HTTPException(status_code=500, detail="Download failed")

    # Upload to Telegram CDN cache (fire-and-forget, won't block streaming)
    try:
        from bot.services.telegram_cache import schedule_upload, get_file_id as _get_fid
        # Only upload if not already cached
        _existing_fid = await _get_fid(video_id)
        if not _existing_fid and mp3_path.exists():
            # Get track metadata for caption
            _track_meta = None
            try:
                from bot.models.base import async_session as _as
                from bot.models.track import Track as _Tr
                from sqlalchemy import select as _sel
                async with _as() as _s:
                    _track_meta = (await _s.execute(
                        _sel(_Tr.title, _Tr.artist, _Tr.duration).where(_Tr.source_id == video_id)
                    )).first()
            except Exception:
                pass
            schedule_upload(
                mp3_path, video_id,
                title=_track_meta[0] if _track_meta else None,
                artist=_track_meta[1] if _track_meta else None,
                duration=_track_meta[2] if _track_meta else None,
            )
    except Exception:
        pass

    # Get file size for Range support
    file_size = mp3_path.stat().st_size
    range_header = request.headers.get("range")
    
    # Handle Range request for partial content
    if range_header:
        # Parse Range: bytes=start-end
        range_match = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
            end = min(end, file_size - 1)
            
            if start >= file_size or start > end:
                raise HTTPException(status_code=416, detail="Range not satisfiable")
            
            chunk_size = end - start + 1
            
            async def iter_file():
                import aiofiles
                async with aiofiles.open(mp3_path, "rb") as f:
                    await f.seek(start)
                    remaining = chunk_size
                    while remaining > 0:
                        read_size = min(65536, remaining)
                        data = await f.read(read_size)
                        if not data:
                            break
                        remaining -= len(data)
                        yield data
            
            return StreamingResponse(
                iter_file(),
                status_code=206,
                media_type="audio/mpeg",
                headers={
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Content-Length": str(chunk_size),
                    "Accept-Ranges": "bytes",
                    "Cache-Control": "public, max-age=86400",
                },
            )
    
    # Full file response
    return FileResponse(
        mp3_path,
        media_type="audio/mpeg",
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
            "Cache-Control": "public, max-age=86400",
        },
    )


def _is_likely_youtube_id(video_id: str) -> bool:
    """Check if video_id looks like a real YouTube ID (11 alphanumeric/dash/underscore chars)."""
    import re as _re
    # Reject known non-YouTube prefixes
    if video_id.startswith(("ym_", "sp_", "vk_", "sc_", "dz_", "am_")):
        return False
    # Reject pure digits (old Yandex IDs leaked as video_id)
    if video_id.isdigit():
        return False
    # Standard YouTube IDs are exactly 11 chars: [a-zA-Z0-9_-]
    if _re.match(r'^[a-zA-Z0-9_-]{8,15}$', video_id):
        return True
    return False


async def _spotify_id_to_query(video_id: str) -> str | None:
    """Look up Spotify track metadata from DB and return 'artist title' search query."""
    try:
        from bot.db import async_session, Track
        async with async_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(Track).where(Track.source_id == video_id).limit(1)
            )
            track = result.scalar_one_or_none()
            if track:
                return f"{track.artist} {track.title}"
    except Exception:
        pass
    # Fallback: strip sp_ prefix and use as-is (Spotify ID won't work, but at least we tried)
    return None


async def _source_id_to_query(video_id: str) -> str | None:
    """Look up any track metadata from DB by source_id and return search query."""
    try:
        from bot.db import async_session, Track
        async with async_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(Track).where(Track.source_id == video_id).limit(1)
            )
            track = result.scalar_one_or_none()
            if track:
                return f"{track.artist} - {track.title}"
    except Exception:
        pass
    # Try Deezer/Apple public API for metadata
    if video_id.startswith("dz_"):
        try:
            from bot.services.deezer_provider import resolve_deezer_track
            info = await resolve_deezer_track(int(video_id[3:]))
            if info:
                return f"{info['uploader']} - {info['title']}"
        except Exception:
            pass
    if video_id.startswith("am_"):
        # Apple tracks have yt_query from charts, but we can't look up by ID without API
        pass
    return None


async def _try_yandex_fallback(query: str, dest: Path) -> Path | None:
    """Try to find and download track from Yandex Music. Returns path or None."""
    try:
        from bot.services.yandex_provider import search_yandex, download_yandex
        results = await search_yandex(query, limit=1)
        if results:
            ym_id = results[0].get("ym_track_id")
            if ym_id:
                return await download_yandex(ym_id, dest)
    except Exception as e:
        logger.debug("Yandex fallback failed for %r: %s", query, e)
    return None


async def _fallback_download(video_id: str, prefix: str, bitrate: int) -> Path:
    """Universal fallback: resolve query → try Yandex → try YouTube."""
    query = await _source_id_to_query(video_id)
    if not query:
        raise HTTPException(status_code=404, detail=f"Track not found: {video_id}")

    dest = settings.DOWNLOAD_DIR / f"{video_id}.mp3"
    # 1. Try Yandex Music
    result = await _try_yandex_fallback(query, dest)
    if result and result.exists():
        return result

    # 2. Fallback to YouTube
    from bot.services.downloader import search_tracks
    results = await search_tracks(query, max_results=1, source="youtube")
    if not results:
        raise HTTPException(status_code=404, detail=f"No match found for: {query}")
    yt_id = results[0].get("video_id", "")
    if not yt_id:
        raise HTTPException(status_code=404, detail=f"No match found for: {query}")
    mp3_path = await download_manager.download(yt_id, bitrate=bitrate)
    # Hardlink so original ID maps to same file
    if not dest.exists() and mp3_path.exists():
        try:
            dest.hardlink_to(mp3_path)
        except OSError:
            import shutil
            shutil.copy2(mp3_path, dest)
    return dest


# ── Helper: Redis player state ──────────────────────────────────────────


async def _resolve_stream_url_cached(video_id: str) -> str | None:
    """Resolve and cache YouTube stream URL. Only works for YouTube IDs."""
    if not _is_likely_youtube_id(video_id):
        return None

    import time as _time

    cached = _stream_url_cache.get(video_id)
    if cached and cached[1] > _time.time():
        return cached[0]

    async with _stream_url_lock:
        existing = _stream_url_inflight.get(video_id)
        if existing is not None:
            return await existing

        future: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()
        _stream_url_inflight[video_id] = future

    try:
        async with _stream_url_resolve_semaphore:
            url = await resolve_youtube_audio_stream_url(video_id)
            if url:
                _stream_url_cache[video_id] = (url, _time.time() + _STREAM_URL_TTL)
            future.set_result(url)
            return url
    except Exception as e:
        future.set_exception(e)
        raise
    finally:
        async with _stream_url_lock:
            _stream_url_inflight.pop(video_id, None)


async def _prefetch_stream_url(video_id: str) -> str | None:
    """Resolve and cache a stream URL without downloading (for prefetch)."""
    if not _is_likely_youtube_id(video_id):
        return None
    import time as _time
    cached = _stream_url_cache.get(video_id)
    if cached and cached[1] > _time.time():
        return cached[0]
    # Skip if file already downloaded
    mp3_path = settings.DOWNLOAD_DIR / f"{video_id}.mp3"
    if mp3_path.exists() and mp3_path.stat().st_size > 10240:
        return None
    return await _resolve_stream_url_cached(video_id)


@app.post("/api/prefetch")
async def prefetch_tracks(
    request: Request,
    x_telegram_init_data: str | None = Header(None),
):
    """Pre-resolve stream URLs for upcoming tracks (fire-and-forget from client)."""
    init_data = x_telegram_init_data
    if not init_data or verify_init_data(init_data) is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    body = await request.json()
    video_ids = body.get("video_ids", [])[:2]  # keep prefetch cheap on small containers
    results = {}
    for vid in video_ids:
        if not isinstance(vid, str):
            continue
        try:
            url = await _prefetch_stream_url(vid)
            if isinstance(url, str):
                results[vid] = "ready"
            else:
                results[vid] = "cached" if (settings.DOWNLOAD_DIR / f"{vid}.mp3").exists() else "pending"
        except Exception:
            results[vid] = "pending"
    return {"prefetched": results}


async def _background_cache(video_id: str, stream_url: str, dest: Path) -> None:
    """Download audio via parallel chunks in background so next play is instant."""
    if dest.exists():
        return
    try:
        from bot.services.http_session import get_session
        session = get_session()
        await download_manager.chunked_download_url(stream_url, dest, session)
        logger.info("Background cache complete: %s", video_id)
    except Exception as e:
        logger.warning("Background cache failed for %s: %s", video_id, e)
        dest.unlink(missing_ok=True)


@app.get("/api/downloads/stats")
async def download_stats():
    """Return download manager statistics."""
    return download_manager.stats


async def _get_redis():
    from bot.services.cache import cache
    return cache.redis


def _state_key(user_id: int) -> str:
    return f"tma:player:{user_id}"


async def _load_state(user_id: int, *, hydrate_covers: bool = True) -> PlayerState:
    r = await _get_redis()
    raw = await r.get(_state_key(user_id))
    if raw:
        state = PlayerState.model_validate_json(raw)
        if hydrate_covers:
            return await _hydrate_state_covers(user_id, state)
        return state
    return PlayerState()


async def _save_state(user_id: int, state: PlayerState) -> None:
    r = await _get_redis()
    await r.setex(_state_key(user_id), 86400, state.model_dump_json())


def _cover_cache_key(source_id: str, source: str | None) -> str:
    return f"{(source or 'youtube').lower()}:{source_id}"


def _get_cached_cover(source_id: str, source: str | None) -> str | None | object:
    import time as _time
    cached = _cover_url_cache.get(_cover_cache_key(source_id, source))
    if not cached:
        return _MISSING
    value, expires_at = cached
    if expires_at <= _time.time():
        _cover_url_cache.pop(_cover_cache_key(source_id, source), None)
        return _MISSING
    return value


def _set_cached_cover(source_id: str, source: str | None, cover_url: str | None) -> None:
    import time as _time
    _cover_url_cache[_cover_cache_key(source_id, source)] = (cover_url, _time.time() + _COVER_URL_TTL)


_MISSING = object()


async def _resolve_cover_url(source_id: str, source: str | None, current_cover: str | None = None, title: str | None = None, artist: str | None = None) -> str | None:
    if current_cover:
        return current_cover

    cached_cover = _get_cached_cover(source_id, source)
    if cached_cover is not _MISSING:
        return cached_cover

    # Check DB for cached cover_url + grab title/artist if missing
    db_title, db_artist = title, artist
    try:
        from sqlalchemy import select
        from bot.models.base import async_session as _as
        from bot.models.track import Track as _Track
        async with _as() as _sess:
            row = (await _sess.execute(
                select(_Track.cover_url, _Track.title, _Track.artist).where(_Track.source_id == source_id)
            )).first()
            if row:
                if row[0]:
                    _set_cached_cover(source_id, source, row[0])
                    return row[0]
                db_title = db_title or row[1]
                db_artist = db_artist or row[2]
    except Exception:
        pass

    normalized_source = (source or "youtube").lower()

    # Source-specific resolvers
    if normalized_source == "yandex" and source_id.startswith("ym_"):
        try:
            from bot.services.yandex_provider import fetch_yandex_track
            track_meta = await fetch_yandex_track(int(source_id[3:]))
            cover_url = track_meta.get("cover_url") if track_meta else None
            if cover_url:
                _set_cached_cover(source_id, source, cover_url)
                await _persist_cover(source_id, cover_url)
                return cover_url
        except Exception:
            pass

    if normalized_source == "spotify" and source_id.startswith("sp_"):
        try:
            from bot.services.spotify_provider import _get_client
            sp = _get_client()
            if sp:
                import asyncio
                track = await asyncio.get_event_loop().run_in_executor(None, sp.track, source_id[3:])
                images = (track.get("album") or {}).get("images") or [] if track else []
                cover_url = images[0]["url"] if images else None
                if cover_url:
                    _set_cached_cover(source_id, source, cover_url)
                    await _persist_cover(source_id, cover_url)
                    return cover_url
        except Exception:
            pass

    if normalized_source == "deezer" and source_id.startswith("dz_"):
        try:
            from bot.services.deezer_provider import fetch_deezer_track
            track_meta = await fetch_deezer_track(int(source_id[3:]))
            cover_url = track_meta.get("cover_url") if track_meta else None
            if cover_url:
                _set_cached_cover(source_id, source, cover_url)
                await _persist_cover(source_id, cover_url)
                return cover_url
        except Exception:
            pass

    # Universal fallback: search Deezer by artist+title (free API, high quality covers)
    query = ""
    if db_artist and db_title:
        query = f"{db_artist} {db_title}"
    elif db_title:
        query = db_title
    if query:
        try:
            from bot.services.deezer_provider import search_deezer
            results = await search_deezer(query, limit=1)
            if results and results[0].get("cover_url"):
                cover_url = results[0]["cover_url"]
                _set_cached_cover(source_id, source, cover_url)
                await _persist_cover(source_id, cover_url)
                return cover_url
        except Exception:
            pass

    _set_cached_cover(source_id, source, None)
    return None


async def _persist_cover(source_id: str, cover_url: str) -> None:
    """Save resolved cover_url to DB (fire-and-forget)."""
    try:
        from bot.models.track import Track as _T
        from bot.models.base import async_session as _as
        async with _as() as s:
            await s.execute(
                _T.__table__.update().where(_T.source_id == source_id).values(cover_url=cover_url)
            )
            await s.commit()
    except Exception:
        pass


async def _resolve_cover_urls_for_tracks(tracks: list[TrackSchema]) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    missing_tracks = [track for track in tracks if track.video_id and not track.cover_url]
    if not missing_tracks:
        return result

    unresolved: list[TrackSchema] = []
    seen_unresolved: set[str] = set()
    unresolved_sources: dict[str, str | None] = {}
    for track in missing_tracks:
        cache_key = _cover_cache_key(track.video_id, track.source)
        cached_cover = _get_cached_cover(track.video_id, track.source)
        if cached_cover is _MISSING:
            if cache_key not in seen_unresolved:
                unresolved.append(track)
                seen_unresolved.add(cache_key)
                unresolved_sources[track.video_id] = track.source
        else:
            result[track.video_id] = cached_cover

    if unresolved:
        try:
            from sqlalchemy import select
            from bot.models.base import async_session as _as
            from bot.models.track import Track as _Track

            source_ids = [track.video_id for track in unresolved]
            async with _as() as _sess:
                rows = (await _sess.execute(
                    select(_Track.source_id, _Track.cover_url).where(_Track.source_id.in_(source_ids))
                )).all()
            for source_id, cover_url in rows:
                if cover_url:
                    result[source_id] = cover_url
                    _set_cached_cover(source_id, unresolved_sources.get(source_id), cover_url)
        except Exception:
            pass

    yandex_tracks: list[TrackSchema] = []
    for track in unresolved:
        if track.video_id in result:
            continue
        normalized_source = (track.source or "youtube").lower()
        if normalized_source == "youtube" and track.video_id:
            cover_url = f"https://i.ytimg.com/vi/{track.video_id}/hqdefault.jpg"
            result[track.video_id] = cover_url
            _set_cached_cover(track.video_id, track.source, cover_url)
        elif normalized_source == "yandex" and track.video_id.startswith("ym_"):
            yandex_tracks.append(track)
        else:
            _set_cached_cover(track.video_id, track.source, None)

    if yandex_tracks:
        async def _fetch_yandex_cover(track: TrackSchema) -> tuple[str, str | None]:
            try:
                from bot.services.yandex_provider import fetch_yandex_track
                track_meta = await fetch_yandex_track(int(track.video_id[3:]))
                cover_url = track_meta.get("cover_url") if track_meta else None
                return track.video_id, cover_url
            except Exception:
                return track.video_id, None

        yandex_results = await asyncio.gather(*(_fetch_yandex_cover(track) for track in yandex_tracks))
        for source_id, cover_url in yandex_results:
            result[source_id] = cover_url
            _set_cached_cover(source_id, "yandex", cover_url)

    return result


async def _hydrate_track_cover(track: TrackSchema, cover_map: dict[str, str | None] | None = None) -> tuple[TrackSchema, bool]:
    cover_url = cover_map.get(track.video_id) if cover_map is not None else None
    if cover_url is None:
        cover_url = await _resolve_cover_url(track.video_id, track.source, track.cover_url)
    if cover_url and cover_url != track.cover_url:
        track.cover_url = cover_url
        return track, True
    return track, False


async def _hydrate_state_covers(user_id: int, state: PlayerState) -> PlayerState:
    changed = False
    tracks_to_hydrate = [*state.queue]
    if state.current_track:
        tracks_to_hydrate.append(state.current_track)
    cover_map = await _resolve_cover_urls_for_tracks(tracks_to_hydrate)

    if state.queue:
        hydrated_queue = await asyncio.gather(*(_hydrate_track_cover(track, cover_map) for track in state.queue))
        state.queue = [track for track, _ in hydrated_queue]
        changed = changed or any(updated for _, updated in hydrated_queue)

    if state.current_track:
        state.current_track, updated = await _hydrate_track_cover(state.current_track, cover_map)
        changed = changed or updated
    elif state.queue and 0 <= state.position < len(state.queue):
        state.current_track = state.queue[state.position]

    if changed:
        await _save_state(user_id, state)

    return state


# ── Endpoints ────────────────────────────────────────────────────────────

@app.get("/api/player/state/{user_id}", response_model=PlayerState)
async def get_player_state(user_id: int, user: dict = Depends(get_current_user)):
    if user.get("id") != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    state = await _load_state(user_id)
    # Always return paused — user must press play after app load.
    # Audio can't autoplay without user gesture (browser policy), so
    # persisted is_playing=True from a previous session is stale.
    state.is_playing = False
    return state


@app.post("/api/player/action", response_model=PlayerState)
async def player_action(body: PlayerAction, user: dict = Depends(get_current_user)):
    user_id = user["id"]
    if not _action_limiter.allow(user_id):
        raise HTTPException(status_code=429, detail="Too many actions, slow down")
    state = await _load_state(user_id, hydrate_covers=False)

    if body.action == "play":
        if body.track_id:
            # Find track in queue or add it
            found = False
            for i, t in enumerate(state.queue):
                if t.video_id == body.track_id:
                    state.position = i
                    found = True
                    break
            if not found and body.track_id:
                # Load track info from DB, fallback to metadata from request
                track = await _get_track_by_source_id(body.track_id)
                if not track and body.track_title:
                    from bot.utils import fmt_duration
                    dur = body.track_duration or 0
                    cover = body.track_cover_url
                    if not cover and (body.track_source or "youtube") == "youtube":
                        cover = f"https://i.ytimg.com/vi/{body.track_id}/hqdefault.jpg"
                    track = TrackSchema(
                        video_id=body.track_id,
                        title=body.track_title,
                        artist=body.track_artist or "Unknown",
                        duration=dur,
                        duration_fmt=fmt_duration(dur),
                        source=body.track_source or "youtube",
                        cover_url=cover,
                    )
                if track:
                    state.queue.append(track)
                    state.position = len(state.queue) - 1
        state.is_playing = True

    elif body.action == "pause":
        state.is_playing = False

    elif body.action == "next":
        if state.queue:
            if state.shuffle:
                import random
                candidates = [i for i in range(len(state.queue)) if i != state.position]
                state.position = random.choice(candidates) if candidates else 0
            else:
                state.position = (state.position + 1) % len(state.queue)
            state.is_playing = True
            if state.position < len(state.queue):
                state.current_track = state.queue[state.position]

    elif body.action == "prev":
        if state.queue:
            state.position = (state.position - 1) % len(state.queue)
            state.is_playing = True
            if state.position < len(state.queue):
                state.current_track = state.queue[state.position]

    elif body.action == "shuffle":
        state.shuffle = not state.shuffle

    elif body.action == "repeat":
        modes = ["off", "one", "all"]
        idx = modes.index(state.repeat_mode) if state.repeat_mode in modes else 0
        state.repeat_mode = modes[(idx + 1) % len(modes)]

    elif body.action == "seek":
        # Seek position stored but actual seeking is client-side
        pass

    elif body.action == "remove":
        # Remove track from queue by video_id
        if body.track_id and state.queue:
            for i, t in enumerate(state.queue):
                if t.video_id == body.track_id:
                    state.queue.pop(i)
                    # Adjust position if needed
                    if i < state.position:
                        state.position -= 1
                    elif i == state.position:
                        # If removing current track, move to next (or prev if last)
                        if state.position >= len(state.queue):
                            state.position = max(0, len(state.queue) - 1)
                        state.is_playing = False
                    break

    elif body.action == "clear":
        state.queue = []
        state.position = 0
        state.current_track = None
        state.is_playing = False

    elif body.action == "add":
        # Add track to queue without playing
        if body.track_id:
            if not any(t.video_id == body.track_id for t in state.queue):
                track = await _get_track_by_source_id(body.track_id)
                if not track and body.track_title:
                    from bot.utils import fmt_duration
                    dur = body.track_duration or 0
                    cover = body.track_cover_url
                    if not cover and (body.track_source or "youtube") == "youtube":
                        cover = f"https://i.ytimg.com/vi/{body.track_id}/hqdefault.jpg"
                    track = TrackSchema(
                        video_id=body.track_id,
                        title=body.track_title,
                        artist=body.track_artist or "Unknown",
                        duration=dur,
                        duration_fmt=fmt_duration(dur),
                        source=body.track_source or "youtube",
                        cover_url=cover,
                    )
                if track:
                    state.queue.append(track)

    # Update current track
    if state.queue and 0 <= state.position < len(state.queue):
        state.current_track = state.queue[state.position]

    await _save_state(user_id, state)
    return state


@app.post("/api/playlist/{playlist_id}/play", response_model=PlayerState)
async def play_playlist(playlist_id: int, user: dict = Depends(get_current_user)):
    """Play all tracks from a playlist - clears queue and adds all tracks."""
    from sqlalchemy import select
    from bot.models.base import async_session
    from bot.models.playlist import Playlist, PlaylistTrack
    from bot.models.track import Track

    user_id = user["id"]

    async with async_session() as session:
        # Verify ownership
        pl = await session.get(Playlist, playlist_id)
        if not pl or pl.user_id != user_id:
            raise HTTPException(status_code=404, detail="Playlist not found")

        q = (
            select(Track)
            .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)
            .where(PlaylistTrack.playlist_id == playlist_id)
            .order_by(PlaylistTrack.position)
        )
        db_tracks = (await session.execute(q)).scalars().all()
        tracks = await _db_tracks_to_schemas(db_tracks)

    if not tracks:
        raise HTTPException(status_code=400, detail="Playlist is empty")

    # Load current state, clear queue, add all tracks
    state = await _load_state(user_id, hydrate_covers=False)
    state.queue = list(tracks)
    state.position = 0
    state.current_track = tracks[0]
    state.is_playing = True

    await _save_state(user_id, state)
    return state


@app.get("/api/playlists/{user_id}", response_model=list[PlaylistSchema])
async def get_playlists(user_id: int, user: dict = Depends(get_current_user)):
    if user.get("id") != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    from sqlalchemy import select, func
    from bot.models.base import async_session
    from bot.models.playlist import Playlist, PlaylistTrack

    async with async_session() as session:
        q = (
            select(
                Playlist.id,
                Playlist.name,
                func.count(PlaylistTrack.id).label("cnt"),
            )
            .outerjoin(PlaylistTrack, PlaylistTrack.playlist_id == Playlist.id)
            .where(Playlist.user_id == user_id)
            .group_by(Playlist.id)
            .order_by(Playlist.created_at.desc())
        )
        rows = (await session.execute(q)).all()
        return [PlaylistSchema(id=r[0], name=r[1], track_count=r[2]) for r in rows]


@app.get("/api/playlist/{playlist_id}/tracks", response_model=list[TrackSchema])
async def get_playlist_tracks(playlist_id: int, user: dict = Depends(get_current_user)):
    from sqlalchemy import select
    from bot.models.base import async_session
    from bot.models.playlist import Playlist, PlaylistTrack
    from bot.models.track import Track

    async with async_session() as session:
        # Verify ownership
        pl = await session.get(Playlist, playlist_id)
        if not pl or pl.user_id != user["id"]:
            raise HTTPException(status_code=404, detail="Playlist not found")

        q = (
            select(Track)
            .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)
            .where(PlaylistTrack.playlist_id == playlist_id)
            .order_by(PlaylistTrack.position)
        )
        tracks = (await session.execute(q)).scalars().all()
        return await _db_tracks_to_schemas(tracks)


@app.get("/api/lyrics/{track_id}", response_model=LyricsResponse)
async def get_lyrics(track_id: str, user: dict = Depends(get_current_user)):
    # Try Redis cache first
    r = await _get_redis()
    cache_key = f"lyrics:{track_id}"
    cached = await r.get(cache_key)
    if cached:
        lyrics = cached.decode() if isinstance(cached, bytes) else cached
        if lyrics == _LYRICS_CACHE_MISS:
            return LyricsResponse(track_id=track_id, lyrics=None)
        return LyricsResponse(track_id=track_id, lyrics=lyrics)

    # Fetch from Genius via search
    lyrics_text = await _fetch_lyrics(track_id)
    if lyrics_text:
        await r.setex(cache_key, _LYRICS_CACHE_TTL, lyrics_text)
    else:
        await r.setex(cache_key, _LYRICS_MISS_TTL, _LYRICS_CACHE_MISS)

    return LyricsResponse(track_id=track_id, lyrics=lyrics_text)


@app.get("/api/search", response_model=SearchResult)
async def search_tracks(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(default=10, ge=1, le=50),
    user: dict = Depends(get_current_user),
):
    uid = int(user.get("id", 0))
    if not _search_limiter.allow(uid):
        raise HTTPException(status_code=429, detail="Too many searches, slow down")
    from bot.services.search_engine import perform_search

    results = await perform_search(q, limit=limit)
    tracks = [
        TrackSchema(
            video_id=r.get("video_id", ""),
            title=r.get("title", "Unknown"),
            artist=r.get("uploader", "Unknown"),
            duration=r.get("duration", 0),
            duration_fmt=r.get("duration_fmt", "0:00"),
            source=r.get("source", "youtube"),
            cover_url=r.get("cover_url") or (f"https://i.ytimg.com/vi/{r.get('video_id', '')}/hqdefault.jpg" if r.get("source", "youtube") == "youtube" else None),
        )
        for r in results
    ]
    # Fire-and-forget: prefetch stream URLs for first 3 YouTube results
    yt_ids = [t.video_id for t in tracks if _is_likely_youtube_id(t.video_id)][:3]
    for vid in yt_ids:
        _fire_task(_prefetch_stream_url(vid))

    return SearchResult(tracks=tracks, total=len(tracks))


# ── AI DJ "Моя Волна" (Infinite recommendations) ────────────────────────

@app.get("/api/wave/{user_id}", response_model=SearchResult)
async def get_wave(
    user_id: int,
    limit: int = Query(default=10, ge=1, le=30),
    mood: str | None = Query(default=None),
    user: dict = Depends(get_current_user),
):
    """AI DJ: generate infinite track recommendations based on user taste.

    Hybrid approach:
    1. If mood → Deezer mood-based discovery
    2. DB-based recommendations (collaborative + content)
    3. Deezer discovery based on user's top artists
    4. Mix: 50% DB recs + 50% Deezer discovery (deduped)
    """
    if user.get("id") != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    from recommender.deezer_discovery import discover_for_user, discover_by_mood

    # If mood specified → pure Deezer mood discovery
    if mood:
        dz_tracks = await discover_by_mood(mood, limit=limit)
        tracks = [
            TrackSchema(
                video_id=r["video_id"], title=r["title"], artist=r["artist"],
                duration=r.get("duration", 0), duration_fmt=r.get("duration_fmt", "0:00"),
                source=r.get("source", "deezer"), cover_url=r.get("cover_url"),
            )
            for r in dz_tracks
        ]
        return SearchResult(tracks=tracks, total=len(tracks))

    # Get DB-based recommendations
    db_recs: list[dict] = []
    if settings.SUPABASE_AI_ENABLED:
        from bot.services.supabase_ai import supabase_ai
        db_recs = await supabase_ai.get_recommendations(user_id, limit=limit)
    else:
        from recommender.ai_dj import get_recommendations
        db_recs = await get_recommendations(user_id, limit=limit)

    # Get user's top artists for Deezer discovery
    top_artists: list[str] = []
    listened_vids: set[str] = set()
    try:
        from bot.models.base import async_session
        from bot.models.track import ListeningHistory, Track
        from sqlalchemy import func, select
        async with async_session() as session:
            artist_r = await session.execute(
                select(Track.artist, func.count(ListeningHistory.id).label("c"))
                .join(Track, Track.id == ListeningHistory.track_id)
                .where(
                    ListeningHistory.user_id == user_id,
                    ListeningHistory.action == "play",
                    Track.artist.isnot(None),
                )
                .group_by(Track.artist)
                .order_by(func.count(ListeningHistory.id).desc())
                .limit(8)
            )
            top_artists = [row[0] for row in artist_r.all() if row[0]]

            vid_r = await session.execute(
                select(Track.source_id)
                .join(ListeningHistory, ListeningHistory.track_id == Track.id)
                .where(ListeningHistory.user_id == user_id)
            )
            listened_vids = {row[0] for row in vid_r.all() if row[0]}
    except Exception:
        pass

    # Deezer discovery (parallel with DB recs already fetched)
    dz_recs: list[dict] = []
    if top_artists:
        try:
            dz_recs = await discover_for_user(top_artists, listened_vids, limit=limit)
        except Exception:
            pass

    # Mix: DB recs first, then fill with Deezer discovery (deduped)
    seen_ids: set[str] = set()
    merged: list[dict] = []

    # Add DB recs
    for r in db_recs:
        vid = r.get("video_id", r.get("source_id", ""))
        if vid and vid not in seen_ids:
            seen_ids.add(vid)
            merged.append(r)

    # Interleave Deezer tracks (insert after every 2 DB tracks)
    dz_idx = 0
    insert_positions = []
    for i in range(2, len(merged) + len(dz_recs), 3):
        if dz_idx < len(dz_recs):
            insert_positions.append((i, dz_recs[dz_idx]))
            dz_idx += 1

    for offset, (pos, track) in enumerate(insert_positions):
        vid = track.get("video_id", "")
        if vid and vid not in seen_ids:
            seen_ids.add(vid)
            merged.insert(min(pos + offset, len(merged)), track)

    # Add remaining Deezer tracks at end
    for t in dz_recs[dz_idx:]:
        vid = t.get("video_id", "")
        if vid and vid not in seen_ids:
            seen_ids.add(vid)
            merged.append(t)

    # Convert to response format
    tracks = [
        TrackSchema(
            video_id=r.get("video_id", r.get("source_id", "")),
            title=r.get("title", "Unknown"),
            artist=r.get("artist", r.get("uploader", "Unknown")),
            duration=r.get("duration", 0),
            duration_fmt=r.get("duration_fmt", "0:00"),
            source=r.get("source", "youtube"),
            cover_url=r.get("cover_url") or _yt_thumb(r.get("video_id", "")),
        )
        for r in merged[:limit]
        if r.get("video_id") or r.get("source_id")
    ]
    return SearchResult(tracks=tracks, total=len(tracks))


# ── Supabase AI Endpoints ────────────────────────────────────────────────


class IngestEventRequest(BaseModel):
    event: str  # "play" | "skip" | "like" | "dislike"
    track: dict
    listen_duration: int | None = None
    source: str = "wave"


class FeedbackRequest(BaseModel):
    feedback: str  # "like" | "dislike" | "skip" | "save" | "share" | "repeat"
    source_id: str | None = None
    context: str | None = None


class AiPlaylistRequest(BaseModel):
    prompt: str
    limit: int = 10


@app.post("/api/ingest")
async def ingest_event(body: IngestEventRequest, user: dict = Depends(get_current_user)):
    """Send a play/skip/like event, upsert track in DB, record listening history."""
    user_id = int(user.get("id", 0))
    track_info = body.track or {}
    source_id = track_info.get("source_id") or ""

    # --- Upsert track & record listening history ---
    track_db_id: int | None = None
    try:
        from bot.db import upsert_track, record_listening_event
        if source_id:
            db_track = await upsert_track(
                source_id=source_id,
                title=track_info.get("title"),
                artist=track_info.get("artist"),
                duration=int(track_info["duration"]) if track_info.get("duration") else None,
                source=track_info.get("source", "youtube"),
                cover_url=track_info.get("cover_url"),
            )
            track_db_id = db_track.id
        await record_listening_event(
            user_id=user_id,
            track_id=track_db_id,
            query=track_info.get("title"),
            action=body.event,
            source=body.source,
            listen_duration=body.listen_duration,
        )
    except Exception:
        pass  # DB errors should never block ingestion

    # --- Gamification: award XP for actions ---
    try:
        from bot.models.base import async_session
        from bot.models.user import User
        from sqlalchemy import select, update
        from datetime import date as dt_date
        xp_map = {"play": 2, "like": 5, "dislike": 1, "skip": 0}
        xp_gain = xp_map.get(body.event, 0)
        if xp_gain > 0:
            async with async_session() as session:
                q = await session.execute(select(User).where(User.id == user["id"]))
                u = q.scalar()
                if u:
                    u.xp = (u.xp or 0) + xp_gain
                    u.level = max(1, ((u.xp or 0) // 100) + 1)
                    today = dt_date.today()
                    if u.last_play_date and u.last_play_date == today:
                        pass
                    elif u.last_play_date and (today - u.last_play_date).days == 1:
                        u.streak_days = (u.streak_days or 0) + 1
                    elif u.last_play_date and (today - u.last_play_date).days > 1:
                        u.streak_days = 1
                    else:
                        u.streak_days = 1
                    u.last_play_date = today
                    badges = list(u.badges or [])
                    if "first_listen" not in badges and body.event == "play":
                        badges.append("first_listen")
                    if "meloman" not in badges and (u.xp or 0) >= 200:
                        badges.append("meloman")
                    if "streak_7" not in badges and (u.streak_days or 0) >= 7:
                        badges.append("streak_7")
                    if "streak_30" not in badges and (u.streak_days or 0) >= 30:
                        badges.append("streak_30")
                    u.badges = badges
                    await session.commit()
    except Exception:
        pass

    if not settings.SUPABASE_AI_ENABLED:
        return {"ok": True}
    from bot.services.supabase_ai import supabase_ai
    ok = await supabase_ai.ingest_event(
        event=body.event,
        user_id=user_id,
        track=body.track,
        listen_duration=body.listen_duration,
        source=body.source,
    )
    return {"ok": ok}


@app.post("/api/feedback")
async def send_feedback(body: FeedbackRequest, user: dict = Depends(get_current_user)):
    """Send explicit like/dislike feedback to Supabase AI."""
    if not settings.SUPABASE_AI_ENABLED:
        return {"ok": False, "reason": "AI not enabled"}
    from bot.services.supabase_ai import supabase_ai
    ok = await supabase_ai.send_feedback(
        user_id=user["id"],
        feedback=body.feedback,
        source_id=body.source_id,
        context=body.context,
    )
    return {"ok": ok}


@app.get("/api/similar/{video_id}", response_model=SearchResult)
async def get_similar(
    video_id: str,
    limit: int = Query(default=10, ge=1, le=30),
    user: dict = Depends(get_current_user),
):
    """Find tracks similar to a given track.

    Tries: Supabase AI embeddings → local DB (same artist) → Deezer discovery.
    """
    results: list[dict] = []

    # Try Supabase AI first
    if settings.SUPABASE_AI_ENABLED:
        from bot.services.supabase_ai import supabase_ai
        results = await supabase_ai.get_similar(source_id=video_id, limit=limit)

    # Try local ai_dj similar
    if not results:
        try:
            from recommender.ai_dj import get_similar_tracks
            from bot.models.base import async_session
            from bot.models.track import Track
            from sqlalchemy import select
            async with async_session() as session:
                row = (await session.execute(
                    select(Track).where(Track.source_id == video_id)
                )).scalar_one_or_none()
                if row:
                    results = await get_similar_tracks(row.id, limit=limit)
        except Exception:
            pass

    # Deezer fallback: search by title + artist
    if not results:
        try:
            from bot.models.base import async_session
            from bot.models.track import Track
            from sqlalchemy import select
            from recommender.deezer_discovery import find_similar_via_deezer
            async with async_session() as session:
                track = (await session.execute(
                    select(Track).where(Track.source_id == video_id)
                )).scalar_one_or_none()
                if track and (track.title or track.artist):
                    results = await find_similar_via_deezer(
                        track.title or "", track.artist or "", limit=limit
                    )
        except Exception:
            pass

    tracks = [
        TrackSchema(
            video_id=r.get("video_id", r.get("source_id", "")),
            title=r.get("title", "Unknown"),
            artist=r.get("artist", r.get("uploader", "Unknown")),
            duration=r.get("duration", 0),
            duration_fmt=r.get("duration_fmt", "0:00"),
            source=r.get("source", "youtube"),
            cover_url=r.get("cover_url") or _yt_thumb(r.get("video_id", "")),
        )
        for r in results
        if r.get("video_id") or r.get("source_id")
    ]
    return SearchResult(tracks=tracks, total=len(tracks))


@app.post("/api/ai-playlist", response_model=SearchResult)
async def create_ai_playlist(body: AiPlaylistRequest, user: dict = Depends(get_current_user)):
    """Generate AI playlist from a text prompt via Supabase Edge Function."""
    if not settings.SUPABASE_AI_ENABLED:
        return SearchResult(tracks=[], total=0)
    from bot.services.supabase_ai import supabase_ai
    results = await supabase_ai.generate_ai_playlist(
        user_id=user["id"],
        prompt=body.prompt,
        limit=body.limit,
    )
    tracks = [
        TrackSchema(
            video_id=r.get("video_id", r.get("source_id", "")),
            title=r.get("title", "Unknown"),
            artist=r.get("artist", "Unknown"),
            duration=r.get("duration", 0),
            duration_fmt=r.get("duration_fmt", "0:00"),
            source=r.get("source", "youtube"),
            cover_url=r.get("cover_url") or (
                f"https://i.ytimg.com/vi/{r.get('video_id', r.get('source_id', ''))}/hqdefault.jpg"
                if r.get("source", "youtube") == "youtube" else None
            ),
        )
        for r in results
        if r.get("video_id") or r.get("source_id")
    ]
    return SearchResult(tracks=tracks, total=len(tracks))


@app.get("/api/trending", response_model=SearchResult)
async def get_trending(
    hours: int = 24, limit: int = 20, genre: str | None = None,
    user: dict = Depends(get_current_user),
):
    """Get currently trending tracks — most played in last N hours."""
    results: list[dict] = []

    if settings.SUPABASE_AI_ENABLED:
        from bot.services.supabase_ai import supabase_ai
        results = await supabase_ai.get_trending(hours=hours, limit=limit, genre=genre)

    # Local DB fallback: most played tracks in last N hours
    if not results:
        from bot.models.base import async_session
        from bot.models.track import ListeningHistory, Track
        from sqlalchemy import func, select
        from datetime import datetime, timedelta, timezone

        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        async with async_session() as session:
            q = (
                select(Track, func.count(ListeningHistory.id).label("plays"))
                .join(ListeningHistory, ListeningHistory.track_id == Track.id)
                .where(
                    ListeningHistory.action == "play",
                    ListeningHistory.created_at >= since,
                )
                .group_by(Track.id)
                .order_by(func.count(ListeningHistory.id).desc())
                .limit(limit)
            )
            rows = (await session.execute(q)).all()
            results = [
                {
                    "video_id": t.source_id, "title": t.title or "Unknown",
                    "artist": t.artist or "Unknown", "duration": t.duration or 0,
                    "duration_fmt": f"{(t.duration or 0) // 60}:{(t.duration or 0) % 60:02d}",
                    "source": t.source or "youtube", "cover_url": t.cover_url,
                }
                for t, plays in rows
            ]

    # If still empty (no listening data yet), fetch Deezer global chart
    if not results:
        from recommender.deezer_discovery import get_genre_tracks
        results = await get_genre_tracks(0, limit=limit)

    tracks = [
        TrackSchema(
            video_id=r.get("video_id", r.get("source_id", "")),
            title=r.get("title", "Unknown"),
            artist=r.get("artist", "Unknown"),
            duration=r.get("duration", 0),
            duration_fmt=r.get("duration_fmt", "0:00"),
            source=r.get("source", "youtube"),
            cover_url=r.get("cover_url") or _yt_thumb(r.get("video_id", "")),
        )
        for r in results
        if r.get("video_id") or r.get("source_id")
    ]
    return SearchResult(tracks=tracks, total=len(tracks))


# ── Track of the Day ──────────────────────────────────────────────────────

_track_of_day_cache: dict = {"date": None, "track": None}


@app.get("/api/track-of-day")
async def track_of_day(user: dict = Depends(get_current_user)):
    """Return a single 'Track of the Day' — cached per calendar day."""
    from datetime import date as dt_date
    today = dt_date.today().isoformat()

    if _track_of_day_cache["date"] == today and _track_of_day_cache["track"]:
        return _track_of_day_cache["track"]

    # Try trending first, then random popular from DB
    track_data = None
    try:
        if settings.SUPABASE_AI_ENABLED:
            from bot.services.supabase_ai import supabase_ai
            results = await supabase_ai.get_trending(hours=48, limit=5)
            if results:
                import random
                r = random.choice(results[:5])
                track_data = {
                    "video_id": r.get("video_id", r.get("source_id", "")),
                    "title": r.get("title", "Unknown"),
                    "artist": r.get("artist", "Unknown"),
                    "duration": r.get("duration", 0),
                    "duration_fmt": r.get("duration_fmt", "0:00"),
                    "source": r.get("source", "youtube"),
                    "cover_url": r.get("cover_url"),
                }
    except Exception:
        pass

    if not track_data:
        # Fallback: most downloaded track from DB
        try:
            from bot.models.base import async_session
            from bot.models.track import Track
            from sqlalchemy import select
            async with async_session() as session:
                q = await session.execute(
                    select(Track).where(Track.downloads > 0).order_by(Track.downloads.desc()).limit(10)
                )
                tracks = q.scalars().all()
                if tracks:
                    import random
                    t = random.choice(tracks[:5])
                    track_data = {
                        "video_id": t.source_id,
                        "title": t.title or "Unknown",
                        "artist": t.artist or "Unknown",
                        "duration": t.duration or 0,
                        "duration_fmt": f"{(t.duration or 0) // 60}:{(t.duration or 0) % 60:02d}",
                        "source": t.source or "youtube",
                        "cover_url": t.cover_url,
                    }
        except Exception:
            pass

    if track_data:
        _track_of_day_cache["date"] = today
        _track_of_day_cache["track"] = track_data

    return track_data or {}


# ── Story Cards API ──────────────────────────────────────────────────────

@app.get("/api/story-card/{video_id}")
async def get_story_card(video_id: str, user: dict = Depends(get_current_user)):
    """Generate a shareable story card image for a track."""
    from bot.services.story_cards import generate_track_card
    import httpx

    # Resolve track info
    title, artist, duration_fmt, cover_bytes = "Unknown", "Unknown", "", None
    try:
        from bot.models.base import async_session
        from bot.models.track import Track
        from sqlalchemy import select
        async with async_session() as session:
            q = await session.execute(select(Track).where(Track.source_id == video_id).limit(1))
            t = q.scalar_one_or_none()
            if t:
                title = t.title or title
                artist = t.artist or artist
                dur = t.duration or 0
                duration_fmt = f"{dur // 60}:{dur % 60:02d}"
                if t.cover_url:
                    try:
                        async with httpx.AsyncClient(timeout=5) as client:
                            resp = await client.get(t.cover_url)
                            if resp.status_code == 200:
                                cover_bytes = resp.content
                    except Exception:
                        pass
    except Exception:
        pass

    png_bytes = generate_track_card(artist, title, video_id, duration_fmt, cover_bytes)
    if not png_bytes:
        raise HTTPException(status_code=500, detail="Story card generation failed")

    from starlette.responses import Response
    return Response(content=png_bytes, media_type="image/png",
                    headers={"Content-Disposition": f'inline; filename="story_{video_id}.png"'})


# ── Music Battles API ───────────────────────────────────────────────────

import random as _random

@app.post("/api/battle/start")
async def start_battle(user: dict = Depends(get_current_user)):
    """Start a music quiz battle — returns 5 rounds with audio snippets and 4 answer choices."""
    from bot.models.base import async_session
    from bot.models.track import Track
    from sqlalchemy import select, func

    async with async_session() as session:
        # Get random tracks that have audio
        q = await session.execute(
            select(Track).where(Track.downloads > 0, Track.title.isnot(None), Track.artist.isnot(None))
            .order_by(func.random()).limit(50)
        )
        all_tracks = q.scalars().all()

    if len(all_tracks) < 8:
        raise HTTPException(status_code=400, detail="Not enough tracks for a battle")

    rounds = []
    used = set()
    for i in range(min(5, len(all_tracks) // 4)):
        # Pick correct answer
        correct = None
        for t in all_tracks:
            if t.source_id not in used:
                correct = t
                used.add(t.source_id)
                break
        if not correct:
            break

        # Pick 3 wrong answers
        wrong = [t for t in all_tracks if t.source_id not in used and t.source_id != correct.source_id]
        _random.shuffle(wrong)
        wrong = wrong[:3]
        for w in wrong:
            used.add(w.source_id)

        options = [{"title": correct.title, "artist": correct.artist, "video_id": correct.source_id}]
        for w in wrong:
            options.append({"title": w.title, "artist": w.artist, "video_id": w.source_id})
        _random.shuffle(options)

        correct_idx = next(i for i, o in enumerate(options) if o["video_id"] == correct.source_id)

        rounds.append({
            "round": i + 1,
            "stream_id": correct.source_id,
            "correct_idx": correct_idx,
            "options": options,
            "cover_url": correct.cover_url,
        })

    return {"rounds": rounds, "total": len(rounds)}


@app.post("/api/battle/score")
async def submit_battle_score(
    body: dict,
    user: dict = Depends(get_current_user),
):
    """Submit battle score — awards XP based on correct answers."""
    correct = body.get("correct", 0)
    total = body.get("total", 5)
    user_id = user["id"]

    xp_earned = correct * 15  # 15 XP per correct answer
    if correct == total:
        xp_earned += 25  # perfect bonus

    try:
        from bot.services.leaderboard import add_xp
        await add_xp(user_id, xp_earned)
    except Exception:
        pass

    return {"correct": correct, "total": total, "xp_earned": xp_earned}


# ── Friends Activity Feed API ───────────────────────────────────────────

@app.get("/api/activity/feed")
async def get_activity_feed(limit: int = 30, user: dict = Depends(get_current_user)):
    """Get recent listening activity from all users (public feed)."""
    from bot.models.base import async_session
    from bot.models.track import ListeningHistory, Track
    from bot.models.user import User
    from sqlalchemy import select, desc

    async with async_session() as session:
        q = await session.execute(
            select(
                ListeningHistory.user_id,
                ListeningHistory.created_at,
                Track.title,
                Track.artist,
                Track.source_id,
                Track.cover_url,
                User.first_name,
                User.username,
            )
            .join(Track, Track.id == ListeningHistory.track_id)
            .join(User, User.id == ListeningHistory.user_id)
            .where(ListeningHistory.action == "play")
            .order_by(desc(ListeningHistory.created_at))
            .limit(min(limit, 50))
        )
        rows = q.all()

    feed = []
    covers_to_resolve: list[tuple[int, str, str | None, str | None, str | None]] = []
    for row in rows:
        sid = row.source_id or ""
        src = None
        if sid.startswith("ym_"): src = "yandex"
        elif sid.startswith("sp_"): src = "spotify"
        elif sid.startswith("dz_"): src = "deezer"
        elif sid.startswith("vk_"): src = "vk"
        else: src = "youtube"

        cover = row.cover_url
        if not cover and sid:
            covers_to_resolve.append((len(feed), sid, src, row.title, row.artist))

        feed.append({
            "user_id": row.user_id,
            "user_name": row.first_name or row.username or "User",
            "track_title": row.title,
            "track_artist": row.artist,
            "video_id": sid,
            "cover_url": cover,
            "played_at": row.created_at.isoformat() if row.created_at else None,
        })

    # Resolve missing covers via Deezer search (best-effort)
    if covers_to_resolve:
        import asyncio
        async def _resolve_one(idx: int, sid: str, src: str | None, title: str | None, artist: str | None):
            try:
                url = await _resolve_cover_url(sid, src, title=title, artist=artist)
                if url:
                    feed[idx]["cover_url"] = url
            except Exception:
                pass
        await asyncio.gather(*[_resolve_one(i, s, src, t, a) for i, s, src, t, a in covers_to_resolve[:15]])

    return {"feed": feed}


# ── Charts API ───────────────────────────────────────────────────────────

@app.post("/api/charts/refresh")
async def refresh_charts(user: dict = Depends(get_current_user)):
    """Force refresh all chart caches."""
    from bot.handlers.charts import _CHART_FETCHERS, _CHART_TTL
    from bot.services.cache import cache
    refreshed = {}
    for src, fetcher in _CHART_FETCHERS.items():
        await cache.redis.delete(f"chart:{src}")
        try:
            tracks = await fetcher()
            if tracks:
                await cache.redis.setex(
                    f"chart:{src}",
                    _CHART_TTL,
                    json.dumps(tracks, ensure_ascii=False),
                )
            refreshed[src] = len(tracks) if tracks else 0
        except Exception as e:
            refreshed[src] = f"error: {e}"
    return refreshed


@app.post("/api/indexer/run")
async def run_indexer_now(user: dict = Depends(get_current_user)):
    """Trigger a manual track indexing run (harvests metadata from all sources)."""
    from bot.services.track_indexer import run_indexer
    results = await run_indexer()
    return {"status": "ok", "indexed": results}


@app.get("/api/crawler/stats")
async def crawler_stats(user: dict = Depends(get_current_user)):
    """Get deep crawler progress stats."""
    from bot.services.deep_crawler import get_crawler_stats
    return await get_crawler_stats()


@app.post("/api/crawler/run")
async def run_crawler_now(user: dict = Depends(get_current_user)):
    """Trigger a manual deep crawl cycle."""
    from bot.services.deep_crawler import run_deep_crawl
    results = await run_deep_crawl()
    return {"status": "ok", "crawled": results}


@app.get("/api/charts")
async def list_charts(user: dict = Depends(get_current_user)):
    """List available chart sources."""
    from bot.handlers.charts import _CHART_LABELS
    return [{"id": k, "label": v} for k, v in _CHART_LABELS.items()]


@app.get("/api/charts/{source}", response_model=SearchResult)
async def get_chart(
    source: str,
    limit: int = Query(default=100, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """Get chart tracks by source."""
    from bot.handlers.charts import _get_chart
    from bot.utils import fmt_duration as _fmt_dur
    tracks_raw = await _get_chart(source)
    if not tracks_raw:
        return SearchResult(tracks=[], total=0)
    tracks = [
        TrackSchema(
            video_id=r.get("video_id", ""),
            title=r.get("title", "Unknown"),
            artist=r.get("artist", "Unknown"),
            duration=r.get("duration", 0),
            duration_fmt=_fmt_dur(r.get("duration", 0)),
            source=r.get("source", "youtube"),
            cover_url=r.get("cover_url") or (
                f"https://i.ytimg.com/vi/{r['video_id']}/hqdefault.jpg"
                if r.get("video_id") and not r.get("video_id", "").startswith(("ym_", "sp_", "vk_"))
                else None
            ),
        )
        for r in tracks_raw[:limit]
        if r.get("title")
    ]
    return SearchResult(tracks=tracks, total=len(tracks))


# ── Playlist CRUD API ────────────────────────────────────────────────────

class CreatePlaylistRequest(BaseModel):
    name: str


class AddTrackToPlaylistRequest(BaseModel):
    video_id: str
    title: str = "Unknown"
    artist: str = "Unknown"
    duration: int = 0
    source: str = "youtube"
    cover_url: str | None = None


class RenamePlaylistRequest(BaseModel):
    name: str


@app.post("/api/playlists", response_model=PlaylistSchema)
async def create_playlist(body: CreatePlaylistRequest, user: dict = Depends(get_current_user)):
    from bot.models.base import async_session
    from bot.models.playlist import Playlist

    name = body.name.strip()[:100]
    if not name:
        raise HTTPException(status_code=400, detail="Name required")

    async with async_session() as session:
        pl = Playlist(user_id=user["id"], name=name)
        session.add(pl)
        await session.commit()
        await session.refresh(pl)
        # Mirror to Supabase
        try:
            from bot.services.supabase_mirror import mirror_playlist_create
            mirror_playlist_create(pl.id, user["id"], name)
        except Exception:
            pass
        return PlaylistSchema(id=pl.id, name=pl.name, track_count=0)


@app.post("/api/playlist/{playlist_id}/tracks", response_model=PlaylistSchema)
async def add_track_to_playlist(
    playlist_id: int,
    body: AddTrackToPlaylistRequest,
    user: dict = Depends(get_current_user),
):
    from sqlalchemy import select, func
    from bot.models.base import async_session
    from bot.models.playlist import Playlist, PlaylistTrack
    from bot.models.track import Track

    async with async_session() as session:
        pl = await session.get(Playlist, playlist_id)
        if not pl:
            raise HTTPException(status_code=404, detail="Playlist not found")
        # Allow owner OR collaborator
        is_owner = pl.user_id == user["id"]
        if not is_owner:
            try:
                from bot.services.cache import cache
                members = await cache.redis.smembers(_collab_key(playlist_id) + ":members")
                if str(user["id"]) not in members:
                    raise HTTPException(status_code=403, detail="Not a collaborator")
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(status_code=403, detail="Not authorized")

        db_track = (
            await session.execute(select(Track).where(Track.source_id == body.video_id))
        ).scalar_one_or_none()
        if db_track is None:
            db_track = Track(
                source_id=body.video_id,
                source=body.source,
                title=body.title,
                artist=body.artist,
                duration=body.duration,
                cover_url=body.cover_url,
                downloads=1,
            )
            session.add(db_track)
            await session.flush()
        else:
            db_track.downloads = (db_track.downloads or 0) + 1
            if body.title and not db_track.title:
                db_track.title = body.title
            if body.artist and not db_track.artist:
                db_track.artist = body.artist
            if body.duration and not db_track.duration:
                db_track.duration = body.duration
            if body.cover_url and not db_track.cover_url:
                db_track.cover_url = body.cover_url

        # Check if already in playlist
        existing = (await session.execute(
            select(PlaylistTrack).where(
                PlaylistTrack.playlist_id == playlist_id,
                PlaylistTrack.track_id == db_track.id,
            )
        )).scalar_one_or_none()

        stats = await session.execute(
            select(
                func.coalesce(func.max(PlaylistTrack.position), -1),
                func.count(PlaylistTrack.id),
            ).where(PlaylistTrack.playlist_id == playlist_id)
        )
        max_pos, cnt = stats.one()
        if existing:
            return PlaylistSchema(id=pl.id, name=pl.name, track_count=cnt)

        pt = PlaylistTrack(playlist_id=playlist_id, track_id=db_track.id, position=max_pos + 1)
        session.add(pt)
        await session.commit()
        await session.refresh(pt)
        # Mirror to Supabase
        try:
            from bot.services.supabase_mirror import mirror_playlist_track_add, mirror_track
            mirror_track(db_track.id, db_track.source_id, db_track.source or "youtube",
                         title=db_track.title, artist=db_track.artist)
            mirror_playlist_track_add(pt.id, playlist_id, db_track.id, max_pos + 1)
        except Exception:
            pass
        return PlaylistSchema(id=pl.id, name=pl.name, track_count=cnt + 1)


@app.delete("/api/playlist/{playlist_id}/tracks/{video_id}")
async def remove_track_from_playlist(
    playlist_id: int,
    video_id: str,
    user: dict = Depends(get_current_user),
):
    from sqlalchemy import select, delete
    from bot.models.base import async_session
    from bot.models.playlist import Playlist, PlaylistTrack
    from bot.models.track import Track

    async with async_session() as session:
        pl = await session.get(Playlist, playlist_id)
        if not pl or pl.user_id != user["id"]:
            raise HTTPException(status_code=404)

        track = (await session.execute(
            select(Track).where(Track.source_id == video_id)
        )).scalar_one_or_none()
        if track:
            await session.execute(
                delete(PlaylistTrack).where(
                    PlaylistTrack.playlist_id == playlist_id,
                    PlaylistTrack.track_id == track.id,
                )
            )
            await session.commit()
            # Mirror to Supabase
            try:
                from bot.services.supabase_mirror import mirror_playlist_track_remove_by_ids
                mirror_playlist_track_remove_by_ids(playlist_id, track.id)
            except Exception:
                pass
    return {"ok": True}


@app.put("/api/playlist/{playlist_id}")
async def rename_playlist(
    playlist_id: int,
    body: RenamePlaylistRequest,
    user: dict = Depends(get_current_user),
):
    from bot.models.base import async_session
    from bot.models.playlist import Playlist

    async with async_session() as session:
        pl = await session.get(Playlist, playlist_id)
        if not pl or pl.user_id != user["id"]:
            raise HTTPException(status_code=404)
        pl.name = body.name.strip()[:100]
        await session.commit()
    return {"ok": True}


@app.delete("/api/playlist/{playlist_id}")
async def delete_playlist(playlist_id: int, user: dict = Depends(get_current_user)):
    from sqlalchemy import delete as sa_delete
    from bot.models.base import async_session
    from bot.models.playlist import Playlist, PlaylistTrack

    async with async_session() as session:
        pl = await session.get(Playlist, playlist_id)
        if not pl or pl.user_id != user["id"]:
            raise HTTPException(status_code=404)
        await session.execute(
            sa_delete(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist_id)
        )
        await session.delete(pl)
        await session.commit()
        # Mirror to Supabase
        try:
            from bot.services.supabase_mirror import mirror_playlist_delete
            mirror_playlist_delete(playlist_id)
        except Exception:
            pass
    return {"ok": True}


# ── Collaborative Playlists (Redis-based, no schema change) ─────────────

import secrets as _secrets

def _collab_key(playlist_id: int) -> str:
    return f"collab:pl:{playlist_id}"

def _collab_invite_key(code: str) -> str:
    return f"collab:invite:{code}"


@app.post("/api/playlist/{playlist_id}/collab/enable")
async def enable_collab(playlist_id: int, user: dict = Depends(get_current_user)):
    """Enable collaborative mode for a playlist. Returns invite code."""
    from bot.models.base import async_session
    from bot.models.playlist import Playlist
    from bot.services.cache import cache

    async with async_session() as session:
        pl = await session.get(Playlist, playlist_id)
        if not pl or pl.user_id != user["id"]:
            raise HTTPException(status_code=404, detail="Playlist not found")

    # Generate invite code
    code = _secrets.token_urlsafe(8)
    key = _collab_key(playlist_id)
    invite_key = _collab_invite_key(code)

    # Store in Redis
    await cache.redis.hset(key, mapping={
        "owner": str(user["id"]),
        "invite_code": code,
        "enabled": "1",
    })
    await cache.redis.sadd(f"{key}:members", str(user["id"]))
    await cache.redis.set(invite_key, str(playlist_id), ex=86400 * 30)  # 30 days

    return {"invite_code": code, "playlist_id": playlist_id}


@app.post("/api/playlist/collab/join/{code}")
async def join_collab(code: str, user: dict = Depends(get_current_user)):
    """Join a collaborative playlist via invite code."""
    from bot.services.cache import cache

    invite_key = _collab_invite_key(code)
    pl_id_raw = await cache.redis.get(invite_key)
    if not pl_id_raw:
        raise HTTPException(status_code=404, detail="Invalid or expired invite code")

    playlist_id = int(pl_id_raw)
    key = _collab_key(playlist_id)

    # Check if collab is enabled
    enabled = await cache.redis.hget(key, "enabled")
    if enabled != "1":
        raise HTTPException(status_code=400, detail="Collaborative mode is not enabled")

    # Add user to members
    await cache.redis.sadd(f"{key}:members", str(user["id"]))

    return {"playlist_id": playlist_id, "joined": True}


@app.get("/api/playlist/{playlist_id}/collab/info")
async def collab_info(playlist_id: int, user: dict = Depends(get_current_user)):
    """Get collaborative playlist info."""
    from bot.services.cache import cache

    key = _collab_key(playlist_id)
    info = await cache.redis.hgetall(key)
    if not info or info.get("enabled") != "1":
        return {"enabled": False}

    members = await cache.redis.smembers(f"{key}:members")
    is_member = str(user["id"]) in members
    is_owner = info.get("owner") == str(user["id"])

    return {
        "enabled": True,
        "invite_code": info.get("invite_code") if is_owner else None,
        "member_count": len(members),
        "is_member": is_member,
        "is_owner": is_owner,
    }


@app.post("/api/playlist/{playlist_id}/collab/disable")
async def disable_collab(playlist_id: int, user: dict = Depends(get_current_user)):
    """Disable collaborative mode (owner only)."""
    from bot.services.cache import cache

    key = _collab_key(playlist_id)
    owner = await cache.redis.hget(key, "owner")
    if owner != str(user["id"]):
        raise HTTPException(status_code=403, detail="Only owner can disable")

    invite_code = await cache.redis.hget(key, "invite_code")
    if invite_code:
        await cache.redis.delete(_collab_invite_key(invite_code))

    await cache.redis.delete(key, f"{key}:members")
    return {"ok": True}


# ── Helpers ──────────────────────────────────────────────────────────────

async def _get_track_by_source_id(source_id: str) -> TrackSchema | None:
    from sqlalchemy import select
    from bot.models.base import async_session
    from bot.models.track import Track

    async with async_session() as session:
        t = (await session.execute(
            select(Track).where(Track.source_id == source_id)
        )).scalar_one_or_none()
        if t:
            schemas = await _db_tracks_to_schemas([t])
            return schemas[0] if schemas else None
    return None


async def _db_track_to_schema(t) -> TrackSchema:
    from bot.utils import fmt_duration
    cover_url = await _resolve_cover_url(t.source_id, t.source)
    return TrackSchema(
        video_id=t.source_id,
        title=t.title or "Unknown",
        artist=t.artist or "Unknown",
        duration=t.duration or 0,
        duration_fmt=fmt_duration(t.duration),
        source=t.source or "youtube",
        file_id=t.file_id,
        cover_url=cover_url,
    )


async def _db_tracks_to_schemas(tracks) -> list[TrackSchema]:
    from bot.utils import fmt_duration

    schemas = [
        TrackSchema(
            video_id=track.source_id,
            title=track.title or "Unknown",
            artist=track.artist or "Unknown",
            duration=track.duration or 0,
            duration_fmt=fmt_duration(track.duration),
            source=track.source or "youtube",
            file_id=track.file_id,
            cover_url=track.cover_url,
        )
        for track in tracks
    ]
    if not schemas:
        return schemas

    cover_map = await _resolve_cover_urls_for_tracks(schemas)
    hydrated = await asyncio.gather(*(_hydrate_track_cover(track, cover_map) for track in schemas))
    return [track for track, _ in hydrated]


async def _fetch_lyrics(track_id: str) -> str | None:
    """Fetch lyrics for a track. Tries LRCLIB (synced) → Genius (plain)."""
    from sqlalchemy import select
    from bot.models.base import async_session
    from bot.models.track import Track

    async with async_session() as session:
        t = (await session.execute(
            select(Track).where(Track.source_id == track_id)
        )).scalar_one_or_none()
        if not t:
            return None

    artist = (t.artist or "").strip()
    title = (t.title or "").strip()
    if not title:
        return None

    # 1) LRCLIB — free, no key, returns synced LRC lyrics
    try:
        import aiohttp
        from bot.services.http_session import get_session
        session = get_session()
        params: dict[str, str | int] = {"track_name": title, "artist_name": artist}
        if t.duration and t.duration > 0:
            params["duration"] = t.duration
        async with session.get(
            "https://lrclib.net/api/get",
            params=params,
            timeout=aiohttp.ClientTimeout(total=8),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                synced = data.get("syncedLyrics")
                if synced and synced.strip():
                    return synced.strip()
                plain = data.get("plainLyrics")
                if plain and plain.strip():
                    return plain.strip()
    except Exception as e:
        logger.debug("LRCLIB lyrics fetch failed: %s", e)

    # 1b) LRCLIB search fallback (looser matching)
    try:
        async with session.get(
            "https://lrclib.net/api/search",
            params={"q": f"{artist} {title}"},
            timeout=aiohttp.ClientTimeout(total=8),
        ) as resp:
            if resp.status == 200:
                results = await resp.json()
                if results and len(results) > 0:
                    best = results[0]
                    synced = best.get("syncedLyrics")
                    if synced and synced.strip():
                        return synced.strip()
                    plain = best.get("plainLyrics")
                    if plain and plain.strip():
                        return plain.strip()
    except Exception as e:
        logger.debug("LRCLIB search failed: %s", e)

    # 2) Genius API fallback (requires GENIUS_TOKEN)
    if settings.GENIUS_TOKEN:
        try:
            query = f"{artist} {title}"
            async with session.get(
                "https://api.genius.com/search",
                params={"q": query},
                headers={"Authorization": f"Bearer {settings.GENIUS_TOKEN}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    hits = data.get("response", {}).get("hits", [])
                    if hits:
                        url = hits[0]["result"]["url"]
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as page_resp:
                            if page_resp.status == 200:
                                from bs4 import BeautifulSoup
                                html = await page_resp.text()
                                soup = BeautifulSoup(html, "lxml")
                                divs = soup.select('div[data-lyrics-container="true"]')
                                if divs:
                                    text = "\n".join(d.get_text(separator="\n") for d in divs)
                                    return text.strip()
        except Exception as e:
            logger.warning("Genius lyrics fetch failed: %s", e)

    return None


# ── Favorites ────────────────────────────────────────────────────────────

def _favorites_key(user_id: int) -> str:
    return f"tma:favorites:{user_id}"


@app.get("/api/favorites/{video_id}")
async def check_favorite(video_id: str, user: dict = Depends(get_current_user)):
    """Check if a track is in user's favorites."""
    r = await _get_redis()
    is_liked = await r.sismember(_favorites_key(user["id"]), video_id)
    return {"liked": bool(is_liked)}


@app.post("/api/favorites/{video_id}")
async def toggle_favorite(video_id: str, user: dict = Depends(get_current_user)):
    """Toggle track in user's favorites."""
    r = await _get_redis()
    key = _favorites_key(user["id"])
    is_member = await r.sismember(key, video_id)
    if is_member:
        await r.srem(key, video_id)
        return {"liked": False}
    else:
        await r.sadd(key, video_id)
        return {"liked": True}


@app.get("/api/favorites/list")
async def list_favorites(
    user: dict = Depends(get_current_user),
    limit: int = Query(default=100, ge=1, le=100),
):
    """List all favorite tracks for current user (Redis set → DB lookup)."""
    user_id = user["id"]
    r = await _get_redis()
    video_ids = await r.smembers(_favorites_key(user_id))
    if not video_ids:
        return {"tracks": []}

    # Decode bytes→str if needed
    ids = [v.decode() if isinstance(v, bytes) else v for v in video_ids][:limit]

    # Lookup metadata from tracks DB
    try:
        from bot.models.base import async_session
        from sqlalchemy import select
        from bot.models.track import Track

        async with async_session() as session:
            q = await session.execute(
                select(Track).where(Track.source_id.in_(ids)).limit(limit)
            )
            tracks = q.scalars().all()
            tracks_map = {t.source_id: t for t in tracks}

            result = []
            for vid in ids:
                t = tracks_map.get(vid)
                if t:
                    result.append({
                        "video_id": t.source_id,
                        "title": t.title or "Unknown",
                        "artist": t.artist or "Unknown",
                        "duration": t.duration or 0,
                        "duration_fmt": f"{(t.duration or 0) // 60}:{(t.duration or 0) % 60:02d}",
                        "source": t.source or "youtube",
                        "cover_url": t.cover_url,
                    })
                else:
                    # Track not in DB yet — return minimal info
                    result.append({
                        "video_id": vid,
                        "title": "Unknown",
                        "artist": "Unknown",
                        "duration": 0,
                        "duration_fmt": "0:00",
                        "source": "youtube",
                        "cover_url": None,
                    })
            return {"tracks": result}
    except Exception:
        # Fallback — return IDs with no metadata
        return {"tracks": [{"video_id": v, "title": "Unknown", "artist": "Unknown", "duration": 0, "duration_fmt": "0:00", "source": "youtube", "cover_url": None} for v in ids]}


@app.get("/api/stats/{user_id}")
async def user_stats(user_id: int, user: dict = Depends(get_current_user)):
    """Listening statistics for profile page — with hard 4s timeout."""
    _defaults = {
        "total_plays": 0, "total_time": 0, "total_favorites": 0,
        "top_artists": [], "top_genres": [], "recent_tracks": [],
        "xp": 0, "level": 1, "streak_days": 0, "badges": [], "member_since": None,
        "next_streak_milestone": None,
    }

    async def _fetch():
        from bot.models.base import async_session
        from sqlalchemy import select, func
        from bot.models.track import ListeningHistory, Track
        from bot.models.user import User

        result = dict(_defaults)

        async with async_session() as session:
            from sqlalchemy import select, func
            from bot.models.track import ListeningHistory, Track
            from bot.models.user import User

            # User info first (fastest, most important)
            u = (await session.execute(select(User).where(User.id == user_id))).scalar()

            total_plays = 0
            total_time = 0
            total_favs = 0
            top_artists: list = []
            top_genres: list = []
            recent: list = []

            # Each sub-query wrapped separately — partial data is better than nothing
            try:
                total_plays = (await session.execute(
                    select(func.count()).where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play")
                )).scalar() or 0
            except Exception:
                pass

            try:
                total_time = (await session.execute(
                    select(func.coalesce(func.sum(ListeningHistory.listen_duration), 0))
                    .where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play")
                )).scalar() or 0
            except Exception:
                pass

            try:
                from bot.models.favorite import FavoriteTrack
                total_favs = (await session.execute(
                    select(func.count()).where(FavoriteTrack.user_id == user_id)
                )).scalar() or 0
            except Exception:
                pass

            try:
                top_artists_q = await session.execute(
                    select(Track.artist, func.count().label("cnt"))
                    .join(ListeningHistory, ListeningHistory.track_id == Track.id)
                    .where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play", Track.artist.isnot(None))
                    .group_by(Track.artist).order_by(func.count().desc()).limit(10)
                )
                top_artists = [{"name": r[0], "count": r[1]} for r in top_artists_q.all()]
            except Exception:
                pass

            try:
                top_genres_q = await session.execute(
                    select(Track.genre, func.count().label("cnt"))
                    .join(ListeningHistory, ListeningHistory.track_id == Track.id)
                    .where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play", Track.genre.isnot(None))
                    .group_by(Track.genre).order_by(func.count().desc()).limit(5)
                )
                top_genres = [{"name": r[0], "count": r[1]} for r in top_genres_q.all()]
            except Exception:
                pass

            try:
                recent_q = await session.execute(
                    select(Track.source_id, Track.title, Track.artist, Track.duration, Track.cover_url, ListeningHistory.created_at)
                    .join(ListeningHistory, ListeningHistory.track_id == Track.id)
                    .where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play")
                    .order_by(ListeningHistory.created_at.desc()).limit(20)
                )
                recent = []
                _rc_to_resolve = []
                for r in recent_q.all():
                    sid = r[0] or ""
                    cover = r[4]
                    if not cover and sid:
                        _rc_to_resolve.append((len(recent), sid, r[1], r[2]))
                    recent.append({
                        "video_id": sid, "title": r[1], "artist": r[2],
                        "duration": r[3] or 0, "duration_fmt": f"{(r[3] or 0) // 60}:{(r[3] or 0) % 60:02d}",
                        "cover_url": cover, "source": "db",
                    })
                if _rc_to_resolve:
                    import asyncio as _aio2
                    async def _res_rc(idx, sid, title, artist):
                        try:
                            url = await _resolve_cover_url(sid, None, title=title, artist=artist)
                            if url: recent[idx]["cover_url"] = url
                        except Exception: pass
                    await _aio2.gather(*[_res_rc(i, s, t, a) for i, s, t, a in _rc_to_resolve[:10]])
            except Exception:
                pass

            streak = u.streak_days if u else 0
            try:
                from bot.services.streak_rewards import get_next_milestone
                next_ms = get_next_milestone(streak)
            except Exception:
                next_ms = None

            return {
                "total_plays": total_plays, "total_time": total_time, "total_favorites": total_favs,
                "top_artists": top_artists, "top_genres": top_genres, "recent_tracks": recent,
                "xp": u.xp if u else 0, "level": u.level if u else 1,
                "streak_days": streak,
                "badges": (u.badges or []) if u else [],
                "member_since": u.created_at.isoformat() if u and u.created_at else None,
                "next_streak_milestone": next_ms,
            }

    try:
        # Hard 4-second server-side timeout — NEVER hang the frontend
        return await asyncio.wait_for(_fetch(), timeout=4.0)
    except asyncio.TimeoutError:
        logger.warning("Stats endpoint timed out for user %s", user_id)
        return _defaults
    except Exception as exc:
        logger.error("Stats endpoint failed for user %s: %s", user_id, exc)
        return _defaults


# ── Leaderboard ────────────────────────────────────────────────────────────

@app.get("/api/leaderboard/{period}")
async def leaderboard(period: str = "weekly", user: dict = Depends(get_current_user)):
    """Get leaderboard (weekly or alltime). Returns top 50 + user's rank."""
    if period not in ("weekly", "alltime"):
        period = "weekly"
    try:
        from bot.services.leaderboard import get_leaderboard, get_user_rank
        from bot.models.base import async_session
        from bot.models.user import User
        from sqlalchemy import select

        user_id = user.get("id", 0)
        entries = await get_leaderboard(period, limit=50)
        my_rank = await get_user_rank(user_id, period)

        # Fetch names for top users
        user_ids = [uid for uid, _ in entries[:50]]
        names: dict[int, dict] = {}
        if user_ids:
            async with async_session() as session:
                result = await session.execute(
                    select(User.id, User.first_name, User.username, User.level, User.xp)
                    .where(User.id.in_(user_ids))
                )
                for row in result.all():
                    names[row[0]] = {
                        "name": row[1] or row[2] or str(row[0]),
                        "level": row[3] or 1,
                        "xp": row[4] or 0,
                    }

        board = []
        for rank, (uid, score) in enumerate(entries, 1):
            info = names.get(uid, {"name": str(uid), "level": 1, "xp": 0})
            board.append({
                "rank": rank,
                "user_id": uid,
                "name": info["name"],
                "level": info["level"],
                "xp": info["xp"],
                "score": int(score),
            })

        return {"period": period, "entries": board, "my_rank": my_rank}
    except Exception as exc:
        logger.error("Leaderboard failed: %s", exc)
        return {"period": period, "entries": [], "my_rank": None}


# ── Weekly Challenges ──────────────────────────────────────────────────────

@app.get("/api/challenges/{user_id}")
async def user_challenges(user_id: int, user: dict = Depends(get_current_user)):
    """Get active weekly challenges and user's progress."""
    try:
        from bot.services.challenges import get_user_challenges
        return await get_user_challenges(user_id)
    except Exception as exc:
        logger.error("Challenges failed for user %s: %s", user_id, exc)
        return {"challenges": [], "week": ""}


# ── Queue Reorder ────────────────────────────────────────────────────────

class ReorderRequest(BaseModel):
    from_index: int
    to_index: int


@app.post("/api/player/reorder", response_model=PlayerState)
async def reorder_queue(body: ReorderRequest, user: dict = Depends(get_current_user)):
    """Reorder a track in the queue."""
    user_id = user["id"]
    state = await _load_state(user_id, hydrate_covers=False)
    
    if not state.queue:
        raise HTTPException(status_code=400, detail="Queue is empty")
    
    from_idx, to_idx = body.from_index, body.to_index
    if not (0 <= from_idx < len(state.queue) and 0 <= to_idx < len(state.queue)):
        raise HTTPException(status_code=400, detail="Invalid index")
    
    # Move track
    track = state.queue.pop(from_idx)
    state.queue.insert(to_idx, track)
    
    # Update position if needed
    if state.position == from_idx:
        state.position = to_idx
    elif from_idx < state.position <= to_idx:
        state.position -= 1
    elif to_idx <= state.position < from_idx:
        state.position += 1
    
    await _save_state(user_id, state)
    return state



# ── Party Playlists (extracted to webapp/routes/party.py) ──────────────
from webapp.routes.party import router as party_router
app.include_router(party_router)

# ── Radio Mode (infinite autoplay) ─────────────────────────────────────

@app.post("/api/radio/next")
async def radio_next(
    request: Request,
    user: dict = Depends(get_current_user),
):
    """
    Flow mode: get next batch of tracks based on seed.
    Uses AI similar → collaborative filtering → Deezer discovery → YouTube fallback.
    """
    body = await request.json()
    seed_id = body.get("seed_video_id", "")
    exclude = body.get("exclude", [])
    limit = min(body.get("limit", 8), 20)

    if not seed_id:
        raise HTTPException(400, "seed_video_id required")

    uid = int(user.get("id", 0))
    exclude_set = set(exclude + [seed_id])
    seen: set[str] = set()
    tracks: list[dict] = []

    def _add(items: list[dict]) -> None:
        for r in items:
            vid = r.get("video_id") or r.get("source_id", "")
            if vid and vid not in exclude_set and vid not in seen:
                seen.add(vid)
                tracks.append({
                    "video_id": vid,
                    "title": r.get("title", "Unknown"),
                    "artist": r.get("artist", r.get("uploader", "Unknown")),
                    "duration": r.get("duration", 0),
                    "duration_fmt": r.get("duration_fmt", "0:00"),
                    "source": r.get("source", "unknown"),
                    "cover_url": r.get("cover_url") or _yt_thumb(vid),
                })

    # ── 1. AI similar tracks (Supabase → local ML → Deezer) ──
    try:
        similar: list[dict] = []
        if settings.SUPABASE_AI_ENABLED:
            from bot.services.supabase_ai import supabase_ai
            similar = await supabase_ai.get_similar(source_id=seed_id, limit=limit)

        if not similar:
            try:
                from recommender.ai_dj import get_similar_tracks
                from bot.models.base import async_session as _as
                from bot.models.track import Track as TrackModel
                from sqlalchemy import select
                async with _as() as session:
                    row = (await session.execute(
                        select(TrackModel).where(TrackModel.source_id == seed_id)
                    )).scalar_one_or_none()
                    if row:
                        similar = await get_similar_tracks(row.id, limit=limit)
            except Exception:
                pass

        if not similar:
            try:
                from bot.models.base import async_session as _as
                from bot.models.track import Track as TrackModel
                from sqlalchemy import select
                from recommender.deezer_discovery import find_similar_via_deezer
                async with _as() as session:
                    track = (await session.execute(
                        select(TrackModel).where(TrackModel.source_id == seed_id)
                    )).scalar_one_or_none()
                    if track and (track.title or track.artist):
                        similar = await find_similar_via_deezer(
                            track.title or "", track.artist or "", limit=limit
                        )
            except Exception:
                pass

        _add(similar)
    except Exception as e:
        logger.error("Flow similar failed: %s", e)

    # ── 2. Personalized recs from user history ──
    if len(tracks) < limit:
        try:
            from recommender.ai_dj import get_recommendations
            recs = await get_recommendations(uid, limit=limit - len(tracks) + 4)
            _add(recs)
        except Exception:
            pass

    # ── 3. Deezer user-based discovery ──
    if len(tracks) < limit:
        try:
            from recommender.deezer_discovery import discover_for_user
            from bot.models.base import async_session as _as
            from bot.models.track import Track as TrackModel
            from bot.models.listening_history import ListeningHistory
            from sqlalchemy import select, func, desc
            async with _as() as session:
                top_artists = [
                    r[0] for r in (await session.execute(
                        select(TrackModel.artist, func.count(ListeningHistory.id).label("cnt"))
                        .join(TrackModel, TrackModel.id == ListeningHistory.track_id)
                        .where(ListeningHistory.user_id == uid, TrackModel.artist.isnot(None))
                        .group_by(TrackModel.artist)
                        .order_by(desc("cnt"))
                        .limit(5)
                    )).all() if r[0]
                ]
            if top_artists:
                dz = await discover_for_user(top_artists, list(exclude_set), limit=limit - len(tracks) + 2)
                _add(dz)
        except Exception:
            pass

    # ── 4. YouTube search fallback ──
    if len(tracks) < limit:
        try:
            from bot.services.search_engine import search as _search
            from bot.models.base import async_session as _as
            from bot.models.track import Track as TrackModel
            from sqlalchemy import select
            async with _as() as session:
                t = (await session.execute(
                    select(TrackModel).where(TrackModel.source_id == seed_id)
                )).scalar_one_or_none()
            if t and t.artist:
                results = await asyncio.wait_for(
                    asyncio.get_running_loop().run_in_executor(
                        None, lambda: _search(f"{t.artist} best songs", max_results=8)
                    ),
                    timeout=5.0,
                )
                for r in (results or []):
                    vid = r.get("video_id") or r.get("id", "")
                    if vid and vid not in exclude_set and vid not in seen:
                        seen.add(vid)
                        tracks.append({
                            "video_id": vid,
                            "title": r.get("title", ""),
                            "artist": r.get("uploader", r.get("artist", "")),
                            "duration": r.get("duration", 0),
                            "duration_fmt": r.get("duration_fmt", "0:00"),
                            "source": "youtube",
                            "cover_url": r.get("cover_url"),
                        })
        except Exception:
            pass

    import random
    random.shuffle(tracks)
    return {"tracks": tracks[:limit]}


# ── Wrapped / Music Recap ──────────────────────────────────────────────

@app.get("/api/wrapped")
async def get_wrapped(user: dict = Depends(get_current_user)):
    """
    Personalized music recap — like Spotify Wrapped but available anytime.
    Returns top artists, genres, moods, listening stats, favorite tracks, etc.
    """
    user_id = user.get("id", 0)

    async def _build():
        from bot.models.base import async_session as _as
        from bot.models.track import ListeningHistory, Track as TrackModel
        from bot.models.user import User
        from bot.models.favorite import FavoriteTrack
        from sqlalchemy import select, func, extract

        async with _as() as session:
            # User info
            u = (await session.execute(select(User).where(User.id == user_id))).scalar()
            if not u:
                raise HTTPException(status_code=404, detail="User not found")

            # Total plays
            total_plays = (await session.execute(
                select(func.count()).where(
                    ListeningHistory.user_id == user_id,
                    ListeningHistory.action == "play",
                )
            )).scalar() or 0

            # Total listening time (seconds)
            total_time = (await session.execute(
                select(func.coalesce(func.sum(ListeningHistory.listen_duration), 0))
                .where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play")
            )).scalar() or 0

            # Total favorites
            total_favs = (await session.execute(
                select(func.count()).where(FavoriteTrack.user_id == user_id)
            )).scalar() or 0

            # Top 10 artists
            top_artists_q = await session.execute(
                select(TrackModel.artist, func.count().label("cnt"))
                .join(ListeningHistory, ListeningHistory.track_id == TrackModel.id)
                .where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play", TrackModel.artist.isnot(None))
                .group_by(TrackModel.artist).order_by(func.count().desc()).limit(10)
            )
            top_artists = [{"name": r[0], "count": r[1]} for r in top_artists_q.all()]

            # Top 5 genres
            top_genres_q = await session.execute(
                select(TrackModel.genre, func.count().label("cnt"))
                .join(ListeningHistory, ListeningHistory.track_id == TrackModel.id)
                .where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play", TrackModel.genre.isnot(None))
                .group_by(TrackModel.genre).order_by(func.count().desc()).limit(5)
            )
            top_genres = [{"name": r[0], "count": r[1]} for r in top_genres_q.all()]

            # Most played track (all time)
            top_track_q = await session.execute(
                select(TrackModel.source_id, TrackModel.title, TrackModel.artist, TrackModel.cover_url, func.count().label("cnt"))
                .join(ListeningHistory, ListeningHistory.track_id == TrackModel.id)
                .where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play")
                .group_by(TrackModel.source_id, TrackModel.title, TrackModel.artist, TrackModel.cover_url)
                .order_by(func.count().desc()).limit(1)
            )
            top_track_row = top_track_q.first()
            top_track = None
            if top_track_row:
                top_track = {
                    "video_id": top_track_row[0], "title": top_track_row[1],
                    "artist": top_track_row[2], "cover_url": top_track_row[3],
                    "play_count": top_track_row[4],
                }

            # Most played tracks (top 10)
            top_tracks_q = await session.execute(
                select(TrackModel.source_id, TrackModel.title, TrackModel.artist, TrackModel.cover_url, TrackModel.duration, func.count().label("cnt"))
                .join(ListeningHistory, ListeningHistory.track_id == TrackModel.id)
                .where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play")
                .group_by(TrackModel.source_id, TrackModel.title, TrackModel.artist, TrackModel.cover_url, TrackModel.duration)
                .order_by(func.count().desc()).limit(10)
            )
            top_tracks = []
            _tt_to_resolve = []
            for r in top_tracks_q.all():
                sid = r[0] or ""
                cover = r[3]
                if not cover and sid:
                    _tt_to_resolve.append((len(top_tracks), sid, r[1], r[2]))
                top_tracks.append({
                    "video_id": sid, "title": r[1], "artist": r[2], "cover_url": cover,
                    "duration": r[4] or 0, "duration_fmt": f"{(r[4] or 0)//60}:{(r[4] or 0)%60:02d}",
                    "play_count": r[5], "source": "db",
                })
            if _tt_to_resolve:
                import asyncio as _aio
                async def _res_tt(idx, sid, title, artist):
                    try:
                        url = await _resolve_cover_url(sid, None, title=title, artist=artist)
                        if url: top_tracks[idx]["cover_url"] = url
                    except Exception: pass
                await _aio.gather(*[_res_tt(i, s, t, a) for i, s, t, a in _tt_to_resolve[:10]])

            # Listening by hour (24 buckets)
            hours_q = await session.execute(
                select(
                    extract("hour", ListeningHistory.created_at).label("hr"),
                    func.count(),
                )
                .where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play")
                .group_by("hr")
            )
            hours_map = {int(r[0]): r[1] for r in hours_q.all()}
            listening_hours = [hours_map.get(h, 0) for h in range(24)]
            peak_hour = max(range(24), key=lambda h: listening_hours[h]) if total_plays > 0 else 12

            # Unique artists count
            unique_artists = (await session.execute(
                select(func.count(func.distinct(TrackModel.artist)))
                .join(ListeningHistory, ListeningHistory.track_id == TrackModel.id)
                .where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play")
            )).scalar() or 0

            # Unique tracks count
            unique_tracks = (await session.execute(
                select(func.count(func.distinct(TrackModel.id)))
                .join(ListeningHistory, ListeningHistory.track_id == TrackModel.id)
                .where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play")
            )).scalar() or 0

            # Personality label based on listening patterns
            personality = "Explorer"
            if top_artists and top_artists[0]["count"] > total_plays * 0.3:
                personality = "Loyalist"
            elif unique_artists > 50:
                personality = "Explorer"
            elif len(top_genres) >= 4:
                personality = "Eclectic"
            elif total_time > 36000:
                personality = "Marathon Runner"
            elif peak_hour >= 22 or peak_hour <= 4:
                personality = "Night Owl"

            return {
                "total_plays": total_plays,
                "total_time": total_time,
                "total_favorites": total_favs,
                "unique_artists": unique_artists,
                "unique_tracks": unique_tracks,
                "top_artists": top_artists,
                "top_genres": top_genres,
                "top_track": top_track,
                "top_tracks": top_tracks,
                "listening_hours": listening_hours,
                "peak_hour": peak_hour,
                "personality": personality,
                "level": u.level if u else 1,
                "xp": u.xp if u else 0,
                "streak_days": u.streak_days if u else 0,
                "member_since": u.created_at.isoformat() if u and u.created_at else None,
            }

    try:
        return await asyncio.wait_for(_build(), timeout=8.0)
    except asyncio.TimeoutError:
        return JSONResponse(
            status_code=504,
            content={"detail": "timeout", "error": "timeout", "total_plays": 0},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Wrapped failed: %s", e)
        return JSONResponse(
            status_code=500,
            content={"detail": "Wrapped build failed", "error": str(e), "total_plays": 0},
        )


# ── Smart Playlists (auto-generated) ──────────────────────────────────

@app.get("/api/smart-playlists")
async def smart_playlists(user: dict = Depends(get_current_user)):
    """
    Auto-generated smart playlists based on user listening data.
    Returns playlist definitions, each with tracks.
    """
    user_id = user.get("id", 0)

    async def _build():
        from bot.models.base import async_session as _as
        from bot.models.track import ListeningHistory, Track as TrackModel
        from bot.models.favorite import FavoriteTrack
        from sqlalchemy import select, func, desc
        from datetime import datetime, timezone, timedelta

        now = datetime.now(timezone.utc)
        playlists = []

        async with _as() as session:
            # 1) Most Played (all time top 20)
            try:
                top_q = await session.execute(
                    select(
                        TrackModel.source_id, TrackModel.title, TrackModel.artist,
                        TrackModel.duration, TrackModel.cover_url,
                        func.count().label("cnt"),
                    )
                    .join(ListeningHistory, ListeningHistory.track_id == TrackModel.id)
                    .where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play")
                    .group_by(TrackModel.source_id, TrackModel.title, TrackModel.artist, TrackModel.duration, TrackModel.cover_url)
                    .order_by(desc("cnt")).limit(20)
                )
                tracks = [{
                    "video_id": r[0], "title": r[1], "artist": r[2],
                    "duration": r[3] or 0,
                    "duration_fmt": f"{(r[3] or 0)//60}:{(r[3] or 0)%60:02d}",
                    "source": "db", "cover_url": r[4],
                } for r in top_q.all()]
                if tracks:
                    playlists.append({
                        "id": "most_played", "name": "Most Played",
                        "icon": "fire", "description": "Your all-time favorites",
                        "tracks": tracks,
                    })
            except Exception:
                pass

            # 2) Recently Discovered (first listen in last 7 days)
            try:
                week_ago = now - timedelta(days=7)
                recent_q = await session.execute(
                    select(
                        TrackModel.source_id, TrackModel.title, TrackModel.artist,
                        TrackModel.duration, TrackModel.cover_url,
                        func.min(ListeningHistory.created_at).label("first_listen"),
                    )
                    .join(ListeningHistory, ListeningHistory.track_id == TrackModel.id)
                    .where(ListeningHistory.user_id == user_id, ListeningHistory.action == "play")
                    .group_by(TrackModel.source_id, TrackModel.title, TrackModel.artist, TrackModel.duration, TrackModel.cover_url)
                    .having(func.min(ListeningHistory.created_at) >= week_ago)
                    .order_by(desc("first_listen")).limit(20)
                )
                tracks = [{
                    "video_id": r[0], "title": r[1], "artist": r[2],
                    "duration": r[3] or 0,
                    "duration_fmt": f"{(r[3] or 0)//60}:{(r[3] or 0)%60:02d}",
                    "source": "db", "cover_url": r[4],
                } for r in recent_q.all()]
                if tracks:
                    playlists.append({
                        "id": "recently_discovered", "name": "Recently Discovered",
                        "icon": "discover", "description": "New tracks from this week",
                        "tracks": tracks,
                    })
            except Exception:
                pass

            # 3) Favorites Mix (shuffled favorites)
            try:
                favs_q = await session.execute(
                    select(
                        TrackModel.source_id, TrackModel.title, TrackModel.artist,
                        TrackModel.duration, TrackModel.cover_url,
                    )
                    .join(FavoriteTrack, FavoriteTrack.track_id == TrackModel.id)
                    .where(FavoriteTrack.user_id == user_id)
                    .order_by(func.random()).limit(25)
                )
                tracks = [{
                    "video_id": r[0], "title": r[1], "artist": r[2],
                    "duration": r[3] or 0,
                    "duration_fmt": f"{(r[3] or 0)//60}:{(r[3] or 0)%60:02d}",
                    "source": "db", "cover_url": r[4],
                } for r in favs_q.all()]
                if tracks:
                    playlists.append({
                        "id": "favorites_mix", "name": "Favorites Mix",
                        "icon": "heart", "description": "Your liked tracks shuffled",
                        "tracks": tracks,
                    })
            except Exception:
                pass

            # 4) Late Night (tracks played after 10pm)
            try:
                from sqlalchemy import extract
                night_q = await session.execute(
                    select(
                        TrackModel.source_id, TrackModel.title, TrackModel.artist,
                        TrackModel.duration, TrackModel.cover_url,
                        func.count().label("cnt"),
                    )
                    .join(ListeningHistory, ListeningHistory.track_id == TrackModel.id)
                    .where(
                        ListeningHistory.user_id == user_id,
                        ListeningHistory.action == "play",
                        extract("hour", ListeningHistory.created_at).in_([22, 23, 0, 1, 2, 3]),
                    )
                    .group_by(TrackModel.source_id, TrackModel.title, TrackModel.artist, TrackModel.duration, TrackModel.cover_url)
                    .order_by(desc("cnt")).limit(20)
                )
                tracks = [{
                    "video_id": r[0], "title": r[1], "artist": r[2],
                    "duration": r[3] or 0,
                    "duration_fmt": f"{(r[3] or 0)//60}:{(r[3] or 0)%60:02d}",
                    "source": "db", "cover_url": r[4],
                } for r in night_q.all()]
                if tracks:
                    playlists.append({
                        "id": "late_night", "name": "Late Night",
                        "icon": "moon", "description": "What you listen to after dark",
                        "tracks": tracks,
                    })
            except Exception:
                pass

        return {"playlists": playlists}

    try:
        return await asyncio.wait_for(_build(), timeout=6.0)
    except asyncio.TimeoutError:
        return {"playlists": []}
    except Exception as e:
        logger.error("Smart playlists failed: %s", e)
        return {"playlists": []}



# ── Live Radio Broadcast (extracted to webapp/routes/broadcast.py) ─────
from webapp.routes.broadcast import router as broadcast_router
app.include_router(broadcast_router)

# ── Frontend SPA serving ────────────────────────────────────────────────

_FRONTEND_DIST = Path(__file__).resolve().parent / "frontend" / "dist"
_ADMIN_DIR = Path(__file__).resolve().parent / "admin"

# ── Admin Panel static serving ──────────────────────────────────────────
@app.get("/admin")
@app.get("/admin/")
async def serve_admin():
    """Serve admin panel index.html."""
    admin_html = _ADMIN_DIR / "index.html"
    if admin_html.is_file():
        return FileResponse(admin_html, media_type="text/html")
    return HTMLResponse("<h1>Admin panel not found</h1>", status_code=404)


_SOUNDS_DIR = Path(__file__).resolve().parent / "static" / "sounds"
if _SOUNDS_DIR.is_dir():
    app.mount("/sounds", StaticFiles(directory=_SOUNDS_DIR), name="ambient_sounds")

_VOICE_DIR = Path(__file__).resolve().parent / "static" / "voice"
_VOICE_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/voice", StaticFiles(directory=_VOICE_DIR), name="dj_voice")

if _FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="static_assets")

    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        """Serve index.html for any non-API route (SPA fallback)."""
        # Don't intercept API routes
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(status_code=404, detail="API route not found")
        file_path = _FRONTEND_DIST / full_path
        if full_path and file_path.is_file() and _FRONTEND_DIST in file_path.resolve().parents:
            return FileResponse(file_path)
        return FileResponse(
            _FRONTEND_DIST / "index.html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )



