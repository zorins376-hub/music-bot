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
import traceback
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

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


def _select_bitrate(pref: str | None, premium: bool) -> int:
    """Map stored quality preference to bitrate for yt-dlp pipeline."""
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
    task.add_done_callback(_background_tasks.discard)
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
_STREAM_URL_TTL = 18000  # 5 hours (YouTube URLs valid ~6h)
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

logger = logging.getLogger(__name__)


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

    # Background track indexer — harvests metadata from charts & APIs into DB
    from bot.services.track_indexer import start_indexer_scheduler
    await start_indexer_scheduler()

    # Deep crawler — runs on separate VPS, not here
    # from bot.services.deep_crawler import start_deep_crawler
    # await start_deep_crawler()

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
_stream_limiter = _RateLimiter(rate=2.0, burst=6)    # stream downloads

@app.get("/health")
async def health():
    import os
    try:
        import resource
        mem_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    except ImportError:
        mem_mb = round(os.getpid() / 1, 1)  # fallback: not meaningful on Windows
    return {
        "status": "ok",
        "uptime_s": int(_time_module.monotonic()),
        "stream_cache_size": len(_stream_url_cache),
        "cover_cache_size": len(_cover_url_cache),
    }


async def _get_or_create_webapp_user(tg_user: dict):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError

    from bot.db import is_admin
    from bot.models.base import async_session
    from bot.models.user import User

    user_id = int(tg_user["id"])
    username = tg_user.get("username")
    first_name = tg_user.get("first_name") or ""
    admin = is_admin(user_id, username)
    now = datetime.now(timezone.utc)
    touch_interval = timedelta(seconds=60)

    for attempt in range(3):
        try:
            async with async_session() as session:
                db_user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
                if db_user is None:
                    db_user = User(
                        id=user_id,
                        username=username,
                        first_name=first_name,
                        is_admin=admin,
                        is_premium=admin,
                    )
                    session.add(db_user)
                    try:
                        await session.commit()
                    except IntegrityError:
                        await session.rollback()
                        db_user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
                        if db_user is None:
                            raise
                        return db_user
                    await session.refresh(db_user)
                    return db_user

                changed = False
                if db_user.username != username:
                    db_user.username = username
                    changed = True
                if db_user.first_name != first_name:
                    db_user.first_name = first_name
                    changed = True
                if db_user.is_admin != admin:
                    db_user.is_admin = admin
                    changed = True

                if db_user.last_active is None or (now - db_user.last_active) >= touch_interval:
                    db_user.last_active = now
                    changed = True

                expired_premium = (
                    not admin
                    and db_user.is_premium
                    and db_user.premium_until is not None
                    and db_user.premium_until < now
                )
                if admin and not db_user.is_premium:
                    db_user.is_premium = True
                    changed = True
                if expired_premium:
                    db_user.is_premium = False
                    changed = True

                if changed:
                    try:
                        await session.commit()
                    except Exception:
                        await session.rollback()
                        raise
                return db_user
        except IntegrityError:
            if attempt < 2:
                continue
            raise
        except asyncio.CancelledError:
            logger.debug("_get_or_create_webapp_user cancelled for user %s", user_id)
            raise
        except Exception as exc:
            if attempt < 2:
                import asyncio as _aio
                await _aio.sleep(0.2 * (attempt + 1))
                continue
            logger.error("_get_or_create_webapp_user failed after 3 attempts: %s", exc)
            raise


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
    x_telegram_init_data: str | None = Header(None),
):
    """Return last N lines from errors.log (admin only)."""
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
    if mp3_path.exists() and not _is_valid_mp3(mp3_path):
        logger.warning("Removing corrupt or invalid file %s", mp3_path)
        mp3_path.unlink()
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
                        raise Exception("Deezer download returned None")
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

                # Fallback: coalesced download via download manager
                mp3_path = await download_manager.download(video_id, bitrate=preferred_bitrate)
        except HTTPException:
            raise
        except Exception as e:
            logger.error("Stream download failed for %s: %s", video_id, e)
            raise HTTPException(status_code=500, detail="Download failed")

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


async def _resolve_cover_url(source_id: str, source: str | None, current_cover: str | None = None) -> str | None:
    if current_cover:
        return current_cover

    cached_cover = _get_cached_cover(source_id, source)
    if cached_cover is not _MISSING:
        return cached_cover

    # Check DB for cached cover_url
    try:
        from sqlalchemy import select
        from bot.models.base import async_session as _as
        from bot.models.track import Track as _Track
        async with _as() as _sess:
            row = (await _sess.execute(
                select(_Track.cover_url).where(_Track.source_id == source_id)
            )).scalar_one_or_none()
            if row:
                _set_cached_cover(source_id, source, row)
                return row
    except Exception:
        pass

    normalized_source = (source or "youtube").lower()
    if normalized_source == "youtube" and source_id:
        cover_url = f"https://i.ytimg.com/vi/{source_id}/hqdefault.jpg"
        _set_cached_cover(source_id, source, cover_url)
        return cover_url

    if normalized_source == "yandex" and source_id.startswith("ym_"):
        try:
            from bot.services.yandex_provider import fetch_yandex_track

            track_meta = await fetch_yandex_track(int(source_id[3:]))
            cover_url = track_meta.get("cover_url") if track_meta else None
            _set_cached_cover(source_id, source, cover_url)
            return cover_url
        except Exception:
            return None

    _set_cached_cover(source_id, source, None)
    return None


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
    """AI DJ: generate infinite track recommendations based on user taste."""
    if user.get("id") != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    recs: list[dict] = []
    if settings.SUPABASE_AI_ENABLED:
        from bot.services.supabase_ai import supabase_ai
        recs = await supabase_ai.get_recommendations(user_id, limit=limit)
    else:
        from recommender.ai_dj import get_recommendations
        recs = await get_recommendations(user_id, limit=limit)

    tracks = [
        TrackSchema(
            video_id=r.get("video_id", r.get("source_id", "")),
            title=r.get("title", "Unknown"),
            artist=r.get("artist", r.get("uploader", "Unknown")),
            duration=r.get("duration", 0),
            duration_fmt=r.get("duration_fmt", "0:00"),
            source=r.get("source", "youtube"),
            cover_url=r.get("cover_url") or (f"https://i.ytimg.com/vi/{r.get('video_id', r.get('source_id', ''))}/hqdefault.jpg" if r.get("source", "youtube") == "youtube" else None),
        )
        for r in recs
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
    """Send a play/skip/like event to Supabase AI for learning user taste."""
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
                    # Level up every 100 XP
                    u.level = max(1, ((u.xp or 0) // 100) + 1)
                    # Streak tracking
                    today = dt_date.today()
                    if u.last_play_date and u.last_play_date == today:
                        pass  # same day
                    elif u.last_play_date and (today - u.last_play_date).days == 1:
                        u.streak_days = (u.streak_days or 0) + 1
                    elif u.last_play_date and (today - u.last_play_date).days > 1:
                        u.streak_days = 1
                    else:
                        u.streak_days = 1
                    u.last_play_date = today
                    # Auto-badges
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
        pass  # gamification errors should never block ingestion

    if not settings.SUPABASE_AI_ENABLED:
        return {"ok": False, "reason": "AI not enabled"}
    from bot.services.supabase_ai import supabase_ai
    ok = await supabase_ai.ingest_event(
        event=body.event,
        user_id=user["id"],
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
    """Find tracks similar to a given track using Supabase AI embeddings."""
    if not settings.SUPABASE_AI_ENABLED:
        return SearchResult(tracks=[], total=0)
    from bot.services.supabase_ai import supabase_ai
    results = await supabase_ai.get_similar(source_id=video_id, limit=limit)
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
    """Get currently trending tracks."""
    if not settings.SUPABASE_AI_ENABLED:
        return SearchResult(tracks=[], total=0)
    from bot.services.supabase_ai import supabase_ai
    results = await supabase_ai.get_trending(hours=hours, limit=limit, genre=genre)
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
    for row in rows:
        feed.append({
            "user_id": row.user_id,
            "user_name": row.first_name or row.username or "User",
            "track_title": row.title,
            "track_artist": row.artist,
            "video_id": row.source_id,
            "cover_url": row.cover_url,
            "played_at": row.created_at.isoformat() if row.created_at else None,
        })

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
    """Fetch lyrics for a track by its source_id."""
    from sqlalchemy import select
    from bot.models.base import async_session
    from bot.models.track import Track

    async with async_session() as session:
        t = (await session.execute(
            select(Track).where(Track.source_id == track_id)
        )).scalar_one_or_none()
        if not t:
            return None

    query = f"{t.artist} {t.title}"

    # Try Genius API if token available
    if settings.GENIUS_TOKEN:
        try:
            import aiohttp
            from bot.services.http_session import get_session
            session = await get_session()
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
                        # Scrape lyrics page
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
                recent = [{
                    "video_id": r[0], "title": r[1], "artist": r[2],
                    "duration": r[3] or 0, "duration_fmt": f"{(r[3] or 0) // 60}:{(r[3] or 0) % 60:02d}",
                    "cover_url": r[4], "source": "db",
                } for r in recent_q.all()]
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


# ── Party Playlists ──────────────────────────────────────────────────────

import math
import secrets
import time
from datetime import datetime, timedelta, timezone

from bot.models.base import async_session
from bot.models.party import PartyChatMessage, PartyEvent, PartyMember, PartyPlaybackState, PartyReaction, PartySession, PartyTrack, PartyTrackVote

# In-memory SSE subscribers: invite_code -> list[asyncio.Queue]
_party_subscribers: dict[str, list[asyncio.Queue]] = {}
_PARTY_MEMBER_TOUCH_INTERVAL = timedelta(seconds=30)


def _party_skip_threshold(member_count: int) -> int:
    if member_count <= 1:
        return 1
    if member_count <= 3:
        return 2
    return min(5, max(3, math.ceil(member_count * 0.5)))


def _iso_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


async def _record_party_event(
    session,
    party_id: int,
    event_type: str,
    message: str,
    actor_id: int | None = None,
    actor_name: str | None = None,
    payload: dict | None = None,
):
    session.add(
        PartyEvent(
            party_id=party_id,
            event_type=event_type,
            actor_id=actor_id,
            actor_name=actor_name,
            message=message[:500],
            payload=payload,
        )
    )


async def _get_party_or_404(session, code: str) -> PartySession:
    from sqlalchemy import select

    result = await session.execute(
        select(PartySession).where(
            PartySession.invite_code == code,
            PartySession.is_active == True,
        )
    )
    party = result.scalar_one_or_none()
    if not party:
        raise HTTPException(status_code=404, detail="Party not found")
    return party


async def _ensure_party_member(session, party: PartySession, user: dict, *, mark_online: bool) -> PartyMember:
    from sqlalchemy import select

    user_id = int(user["id"])
    name = user.get("first_name") or user.get("username") or f"User {user_id}"
    result = await session.execute(
        select(PartyMember).where(
            PartyMember.party_id == party.id,
            PartyMember.user_id == user_id,
        )
    )
    member = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if member is None:
        member = PartyMember(
            party_id=party.id,
            user_id=user_id,
            display_name=name,
            role="dj" if party.creator_id == user_id else "listener",
            is_online=mark_online,
            joined_at=now,
            last_seen_at=now,
        )
        session.add(member)
    else:
        if member.display_name != name:
            member.display_name = name
        if party.creator_id == user_id:
            member.role = "dj"
        should_touch_presence = mark_online or member.last_seen_at is None
        if not should_touch_presence and member.last_seen_at is not None:
            should_touch_presence = (now - member.last_seen_at) >= _PARTY_MEMBER_TOUCH_INTERVAL
        if should_touch_presence:
            member.last_seen_at = now
        if mark_online and not member.is_online:
            member.is_online = True
    return member


async def _get_or_create_party_playback(session, party_id: int) -> PartyPlaybackState:
    from sqlalchemy import select

    result = await session.execute(select(PartyPlaybackState).where(PartyPlaybackState.party_id == party_id))
    playback = result.scalar_one_or_none()
    if playback is None:
        playback = PartyPlaybackState(party_id=party_id)
        session.add(playback)
        await session.flush()
    return playback


async def _get_party_playback(session, party_id: int) -> PartyPlaybackState | None:
    from sqlalchemy import select

    result = await session.execute(select(PartyPlaybackState).where(PartyPlaybackState.party_id == party_id))
    return result.scalar_one_or_none()


async def _normalize_party_positions(session, party_id: int):
    from sqlalchemy import select

    tracks = (
        await session.execute(
            select(PartyTrack)
            .where(PartyTrack.party_id == party_id)
            .order_by(PartyTrack.position, PartyTrack.id)
        )
    ).scalars().all()
    changed = False
    for idx, track in enumerate(tracks):
        if track.position != idx:
            track.position = idx
            changed = True
    return changed


async def _build_party_schema(session, party: PartySession, viewer_id: int | None = None) -> PartySchema:
    from sqlalchemy import func, select

    tracks = (
        await session.execute(
            select(PartyTrack)
            .where(PartyTrack.party_id == party.id)
            .order_by(PartyTrack.position, PartyTrack.id)
        )
    ).scalars().all()
    track_ids = [t.id for t in tracks]
    vote_counts: dict[int, int] = {}
    reaction_counts: dict[str, int] = {}
    if track_ids:
        rows = await session.execute(
            select(PartyTrackVote.track_id, func.count())
            .where(
                PartyTrackVote.track_id.in_(track_ids),
                PartyTrackVote.vote_type == "skip",
            )
            .group_by(PartyTrackVote.track_id)
        )
        vote_counts = {track_id: count for track_id, count in rows.all()}

    current_track = next((t for t in tracks if t.position == party.current_position), None)
    if current_track is not None:
        reaction_rows = await session.execute(
            select(PartyReaction.emoji, func.count())
            .where(PartyReaction.track_id == current_track.id)
            .group_by(PartyReaction.emoji)
        )
        reaction_counts = {emoji: count for emoji, count in reaction_rows.all()}

    members = (
        await session.execute(
            select(PartyMember)
            .where(PartyMember.party_id == party.id)
            .order_by(PartyMember.is_online.desc(), PartyMember.joined_at.asc())
        )
    ).scalars().all()
    events = (
        await session.execute(
            select(PartyEvent)
            .where(PartyEvent.party_id == party.id)
            .order_by(PartyEvent.created_at.desc())
            .limit(12)
        )
    ).scalars().all()
    events = list(reversed(events))
    chat_messages = (
        await session.execute(
            select(PartyChatMessage)
            .where(PartyChatMessage.party_id == party.id)
            .order_by(PartyChatMessage.created_at.desc())
            .limit(30)
        )
    ).scalars().all()
    chat_messages = list(reversed(chat_messages))

    playback = await _get_party_playback(session, party.id)
    online_count = sum(1 for member in members if member.is_online)
    viewer_role = "listener"
    if viewer_id is not None:
        if viewer_id == party.creator_id:
            viewer_role = "dj"
        else:
            viewer_member = next((m for m in members if m.user_id == viewer_id), None)
            if viewer_member:
                viewer_role = viewer_member.role

    return PartySchema(
        id=party.id,
        invite_code=party.invite_code,
        creator_id=party.creator_id,
        name=party.name,
        is_active=party.is_active,
        current_position=party.current_position,
        member_count=online_count,
        skip_threshold=_party_skip_threshold(online_count),
        viewer_role=viewer_role,
        members=[
            PartyMemberSchema(
                user_id=m.user_id,
                display_name=m.display_name,
                role=m.role,
                is_online=bool(m.is_online),
            )
            for m in members
        ],
        events=[
            PartyEventSchema(
                id=e.id,
                event_type=e.event_type,
                actor_id=e.actor_id,
                actor_name=e.actor_name,
                message=e.message,
                payload=e.payload,
                created_at=_iso_dt(e.created_at),
            )
            for e in events
        ],
        chat_messages=[
            PartyChatMessageSchema(
                id=message.id,
                user_id=message.user_id,
                display_name=message.display_name,
                message=message.message,
                created_at=_iso_dt(message.created_at),
            )
            for message in chat_messages
        ],
        playback=PartyPlaybackStateSchema(
            track_position=playback.track_position if playback is not None else 0,
            action=playback.action if playback is not None else "idle",
            seek_position=playback.seek_position if playback is not None else 0,
            updated_by=playback.updated_by if playback is not None else None,
            updated_at=_iso_dt(playback.updated_at) if playback is not None else None,
        ),
        current_reactions=reaction_counts,
        tracks=[
            PartyTrackSchema(
                video_id=t.video_id,
                title=t.title,
                artist=t.artist,
                duration=t.duration,
                duration_fmt=t.duration_fmt,
                source=t.source,
                cover_url=t.cover_url,
                added_by=t.added_by,
                added_by_name=t.added_by_name,
                skip_votes=vote_counts.get(t.id, 0),
                position=t.position,
            )
            for t in tracks
        ],
    )


async def _get_party_with_tracks(code: str, viewer_id: int | None = None) -> PartySchema:
    """Load party session by invite code with all extended state."""
    async with async_session() as session:
        party = await _get_party_or_404(session, code)
        return await _build_party_schema(session, party, viewer_id)


async def _commit_and_build_party_schema(
    session,
    party: PartySession,
    viewer_id: int | None = None,
) -> PartySchema:
    """Flush pending party changes when needed and reuse the same session to build the response."""
    if session.new or session.dirty or session.deleted:
        await session.commit()
    return await _build_party_schema(session, party, viewer_id)


async def _notify_party(code: str, event: str, data: dict | None = None):
    """Send SSE event to all subscribers of a party."""
    subs = _party_subscribers.get(code, [])
    payload = json.dumps({"event": event, "data": data or {}}, ensure_ascii=False)
    dead: list[asyncio.Queue] = []
    for q in subs:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        try:
            subs.remove(q)
        except ValueError:
            pass


async def _notify_party_state(code: str, event: str, data: dict | None = None):
    await _notify_party(code, event, data)


@app.post("/api/party", response_model=PartySchema)
async def create_party(body: PartyCreateRequest, user: dict = Depends(get_current_user)):
    """Create a new party session."""
    # Ensure user exists in DB (FK constraint on creator_id → users.id)
    await _get_or_create_webapp_user(user)
    code = secrets.token_urlsafe(8)[:10]
    async with async_session() as session:
        from sqlalchemy import select, func
        # Limit active parties per user to 3
        count_result = await session.execute(
            select(func.count()).where(
                PartySession.creator_id == user["id"],
                PartySession.is_active == True,
            )
        )
        if (count_result.scalar() or 0) >= 3:
            raise HTTPException(status_code=400, detail="Max 3 active parties")

        party = PartySession(
            invite_code=code,
            creator_id=user["id"],
            name=body.name[:100],
        )
        session.add(party)
        await session.flush()
        await _ensure_party_member(session, party, user, mark_online=False)
        await _get_or_create_party_playback(session, party.id)
        await _record_party_event(
            session,
            party.id,
            "party_created",
            f"{user.get('first_name', 'DJ')} создал пати",
            actor_id=user["id"],
            actor_name=user.get("first_name", "DJ"),
        )
        party_schema = await _commit_and_build_party_schema(session, party, int(user["id"]))

    return party_schema


@app.get("/api/party/{code}", response_model=PartySchema)
async def get_party(code: str, user: dict = Depends(get_current_user)):
    """Get party state with tracks."""
    await _get_or_create_webapp_user(user)
    async with async_session() as session:
        party = await _get_party_or_404(session, code)
        await _ensure_party_member(session, party, user, mark_online=False)
        party_schema = await _commit_and_build_party_schema(session, party, int(user["id"]))
    return party_schema


@app.post("/api/party/{code}/tracks", response_model=PartySchema)
async def add_party_track(code: str, body: PartyAddTrackRequest, user: dict = Depends(get_current_user)):
    """Add a track to party queue."""
    async with async_session() as session:
        from sqlalchemy import select, func
        party = await _get_party_or_404(session, code)
        await _ensure_party_member(session, party, user, mark_online=False)

        # Prevent duplicate tracks in queue (same video_id that hasn't played yet)
        existing_dup = await session.execute(
            select(PartyTrack.id).where(
                PartyTrack.party_id == party.id,
                PartyTrack.video_id == body.video_id,
                PartyTrack.position >= party.current_position,
            ).limit(1)
        )
        if existing_dup.scalar() is not None:
            raise HTTPException(status_code=409, detail="Track already in queue")

        # Get max position
        max_pos_result = await session.execute(
            select(func.coalesce(func.max(PartyTrack.position), -1))
            .where(PartyTrack.party_id == party.id)
        )
        max_pos = max_pos_result.scalar() or 0

        track = PartyTrack(
            party_id=party.id,
            video_id=body.video_id,
            title=body.title,
            artist=body.artist,
            duration=body.duration,
            duration_fmt=body.duration_fmt,
            source=body.source,
            cover_url=body.cover_url,
            added_by=user["id"],
            added_by_name=user.get("first_name", "User"),
            position=max_pos + 1,
        )
        session.add(track)
        await session.flush()
        await _record_party_event(
            session,
            party.id,
            "track_added",
            f"{user.get('first_name', 'User')} добавил(а) {body.title}",
            actor_id=user["id"],
            actor_name=user.get("first_name", "User"),
            payload={"video_id": body.video_id, "title": body.title},
        )
        party_schema = await _commit_and_build_party_schema(session, party, int(user["id"]))

    await _notify_party_state(code, "track_added", {
        "video_id": body.video_id,
        "title": body.title,
        "artist": body.artist,
        "added_by_name": user.get("first_name", "User"),
    })
    return party_schema


@app.post("/api/party/{code}/tracks/{video_id}/play-next", response_model=PartySchema)
async def play_next_party_track(code: str, video_id: str, user: dict = Depends(get_current_user)):
    """Move a queued track to play next."""
    async with async_session() as session:
        from sqlalchemy import select

        party = await _get_party_or_404(session, code)
        member = await _ensure_party_member(session, party, user, mark_online=False)
        if member.role not in {"dj", "cohost"} and party.creator_id != user["id"]:
            raise HTTPException(status_code=403, detail="Only DJ/co-host can reorder tracks")

        tracks = (
            await session.execute(
                select(PartyTrack)
                .where(PartyTrack.party_id == party.id)
                .order_by(PartyTrack.position, PartyTrack.id)
            )
        ).scalars().all()
        target = next((t for t in tracks if t.video_id == video_id), None)
        if target is None:
            raise HTTPException(status_code=404, detail="Track not found")
        if target.position <= party.current_position:
            raise HTTPException(status_code=400, detail="Track is already playing or finished")

        upcoming = [t for t in tracks if t.position > party.current_position]
        upcoming = [t for t in upcoming if t.video_id != video_id]
        upcoming.insert(0, target)
        start_pos = party.current_position + 1
        for idx, track in enumerate(upcoming):
            track.position = start_pos + idx
        await _record_party_event(
            session,
            party.id,
            "queue_reordered",
            f"{user.get('first_name', 'DJ')} перенёс(ла) {target.title} в play next",
            actor_id=user["id"],
            actor_name=user.get("first_name", "DJ"),
            payload={"video_id": video_id, "mode": "play_next"},
        )
        party_schema = await _commit_and_build_party_schema(session, party, int(user["id"]))

    await _notify_party_state(code, "queue_reordered", {"video_id": video_id, "mode": "play_next"})
    return party_schema


@app.post("/api/party/{code}/reorder", response_model=PartySchema)
async def reorder_party_tracks(code: str, body: PartyReorderRequest, user: dict = Depends(get_current_user)):
    """Reorder queued tracks for DJ/co-hosts."""
    async with async_session() as session:
        from sqlalchemy import select

        party = await _get_party_or_404(session, code)
        member = await _ensure_party_member(session, party, user, mark_online=False)
        if member.role not in {"dj", "cohost"} and party.creator_id != user["id"]:
            raise HTTPException(status_code=403, detail="Only DJ/co-host can reorder tracks")
        if body.from_position <= party.current_position or body.to_position <= party.current_position:
            raise HTTPException(status_code=400, detail="Only upcoming tracks can be reordered")

        tracks = (
            await session.execute(
                select(PartyTrack)
                .where(PartyTrack.party_id == party.id)
                .order_by(PartyTrack.position, PartyTrack.id)
            )
        ).scalars().all()
        upcoming = [t for t in tracks if t.position > party.current_position]
        from_index = next((idx for idx, track in enumerate(upcoming) if track.position == body.from_position), None)
        to_index = next((idx for idx, track in enumerate(upcoming) if track.position == body.to_position), None)
        if from_index is None or to_index is None:
            raise HTTPException(status_code=404, detail="Track position not found")

        track = upcoming.pop(from_index)
        upcoming.insert(to_index, track)
        start_pos = party.current_position + 1
        for idx, queued_track in enumerate(upcoming):
            queued_track.position = start_pos + idx

        await _record_party_event(
            session,
            party.id,
            "queue_reordered",
            f"{user.get('first_name', 'DJ')} изменил(а) порядок очереди",
            actor_id=user["id"],
            actor_name=user.get("first_name", "DJ"),
            payload={"from_position": body.from_position, "to_position": body.to_position},
        )
        party_schema = await _commit_and_build_party_schema(session, party, int(user["id"]))

    await _notify_party_state(code, "queue_reordered", {"from_position": body.from_position, "to_position": body.to_position})
    return party_schema


@app.delete("/api/party/{code}/tracks/{video_id}")
async def remove_party_track(code: str, video_id: str, user: dict = Depends(get_current_user)):
    """Remove a track from party queue (creator only)."""
    async with async_session() as session:
        from sqlalchemy import delete, select

        party = await _get_party_or_404(session, code)
        member = await _ensure_party_member(session, party, user, mark_online=False)
        if member.role not in {"dj", "cohost"} and party.creator_id != user["id"]:
            raise HTTPException(status_code=403, detail="Only DJ/co-host can remove tracks")

        track = (
            await session.execute(
                select(PartyTrack).where(
                    PartyTrack.party_id == party.id,
                    PartyTrack.video_id == video_id,
                )
            )
        ).scalar_one_or_none()
        if track is None:
            raise HTTPException(status_code=404, detail="Track not found")

        await session.execute(delete(PartyTrackVote).where(PartyTrackVote.track_id == track.id))
        removed_position = track.position
        await session.execute(delete(PartyTrack).where(PartyTrack.id == track.id))
        # Adjust current_position if a played/current track was removed
        if removed_position < party.current_position:
            party.current_position = max(0, party.current_position - 1)
        await _normalize_party_positions(session, party.id)
        await _record_party_event(
            session,
            party.id,
            "track_removed",
            f"{user.get('first_name', 'DJ')} удалил(а) {track.title}",
            actor_id=user["id"],
            actor_name=user.get("first_name", "DJ"),
            payload={"video_id": video_id},
        )
        await session.commit()

    await _notify_party_state(code, "track_removed", {"video_id": video_id})
    return {"ok": True}


@app.post("/api/party/{code}/skip")
async def skip_party_track(code: str, user: dict = Depends(get_current_user)):
    """Vote to skip or force-skip (DJ). Auto-skips at 3 votes."""
    async with async_session() as session:
        from sqlalchemy import delete, func, select

        party = await _get_party_or_404(session, code)
        member = await _ensure_party_member(session, party, user, mark_online=False)
        can_control = member.role in {"dj", "cohost"} or party.creator_id == user["id"]

        # Get current track
        track_result = await session.execute(
            select(PartyTrack).where(
                PartyTrack.party_id == party.id,
                PartyTrack.position == party.current_position,
            )
        )
        current_track = track_result.scalar_one_or_none()
        if current_track is None:
            raise HTTPException(status_code=400, detail="No active track")

        member_count = (
            await session.execute(
                select(func.count()).where(
                    PartyMember.party_id == party.id,
                    PartyMember.is_online == True,
                )
            )
        ).scalar() or 0
        threshold = _party_skip_threshold(int(member_count))

        skip = can_control
        votes = 0
        if not can_control:
            existing_vote = (
                await session.execute(
                    select(PartyTrackVote).where(
                        PartyTrackVote.track_id == current_track.id,
                        PartyTrackVote.user_id == user["id"],
                        PartyTrackVote.vote_type == "skip",
                    )
                )
            ).scalar_one_or_none()
            if existing_vote:
                raise HTTPException(status_code=400, detail="Already voted to skip")
            session.add(
                PartyTrackVote(
                    party_id=party.id,
                    track_id=current_track.id,
                    user_id=user["id"],
                    vote_type="skip",
                )
            )
            await session.flush()
            votes = (
                await session.execute(
                    select(func.count()).where(
                        PartyTrackVote.track_id == current_track.id,
                        PartyTrackVote.vote_type == "skip",
                    )
                )
            ).scalar() or 0
            skip = votes >= threshold
            await _record_party_event(
                session,
                party.id,
                "skip_vote",
                f"{user.get('first_name', 'User')} проголосовал(а) за skip",
                actor_id=user["id"],
                actor_name=user.get("first_name", "User"),
                payload={"votes": votes, "threshold": threshold},
            )

        if skip:
            await session.execute(delete(PartyTrackVote).where(PartyTrackVote.track_id == current_track.id))
            party.current_position += 1
            playback = await _get_or_create_party_playback(session, party.id)
            playback.track_position = party.current_position
            playback.action = "play"
            playback.seek_position = 0
            playback.updated_by = int(user["id"])
            playback.updated_at = datetime.now(timezone.utc)
            await _record_party_event(
                session,
                party.id,
                "next_track",
                f"{user.get('first_name', 'DJ')} переключил(а) следующий трек",
                actor_id=user["id"],
                actor_name=user.get("first_name", "DJ"),
                payload={"position": party.current_position},
            )

        party_schema = await _commit_and_build_party_schema(session, party, int(user["id"]))

    if skip:
        await _notify_party_state(code, "next", {"position": party.current_position})
    else:
        await _notify_party_state(code, "vote_skip", {"votes": votes, "threshold": threshold})

    return party_schema


@app.post("/api/party/{code}/members/{member_user_id}/role", response_model=PartySchema)
async def update_party_member_role(
    code: str,
    member_user_id: int,
    body: PartyRoleUpdateRequest,
    user: dict = Depends(get_current_user),
):
    """Promote or demote co-hosts inside a party."""
    if body.role not in {"cohost", "listener"}:
        raise HTTPException(status_code=400, detail="Unsupported role")

    async with async_session() as session:
        from sqlalchemy import select

        party = await _get_party_or_404(session, code)
        await _ensure_party_member(session, party, user, mark_online=False)
        if party.creator_id != user["id"]:
            raise HTTPException(status_code=403, detail="Only DJ can change roles")
        if member_user_id == party.creator_id:
            raise HTTPException(status_code=400, detail="DJ role cannot be changed")

        target = (
            await session.execute(
                select(PartyMember).where(
                    PartyMember.party_id == party.id,
                    PartyMember.user_id == member_user_id,
                )
            )
        ).scalar_one_or_none()
        if target is None:
            raise HTTPException(status_code=404, detail="Member not found")

        target.role = body.role
        await _record_party_event(
            session,
            party.id,
            "role_updated",
            f"{target.display_name or 'Участник'} теперь {body.role}",
            actor_id=user["id"],
            actor_name=user.get("first_name", "DJ"),
            payload={"user_id": member_user_id, "role": body.role},
        )
        party_schema = await _commit_and_build_party_schema(session, party, int(user["id"]))

    await _notify_party_state(code, "role_updated", {"user_id": member_user_id, "role": body.role})
    return party_schema


@app.post("/api/party/{code}/playback", response_model=PartySchema)
async def sync_party_playback(code: str, body: PartyPlaybackRequest, user: dict = Depends(get_current_user)):
    """Sync party playback for all listeners (DJ/co-host)."""
    if body.action not in {"play", "pause", "seek"}:
        raise HTTPException(status_code=400, detail="Unsupported playback action")

    async with async_session() as session:
        party = await _get_party_or_404(session, code)
        member = await _ensure_party_member(session, party, user, mark_online=False)
        if member.role not in {"dj", "cohost"} and party.creator_id != user["id"]:
            raise HTTPException(status_code=403, detail="Only DJ/co-host can sync playback")

        playback = await _get_or_create_party_playback(session, party.id)
        playback.action = body.action
        playback.track_position = max(0, body.track_position)
        playback.seek_position = max(0, body.seek_position)
        playback.updated_by = int(user["id"])
        playback.updated_at = datetime.now(timezone.utc)
        if body.action == "play":
            party.current_position = max(0, body.track_position)

        await _record_party_event(
            session,
            party.id,
            "playback_sync",
            f"{user.get('first_name', 'DJ')} синхронизировал(а) playback: {body.action}",
            actor_id=user["id"],
            actor_name=user.get("first_name", "DJ"),
            payload={
                "action": body.action,
                "track_position": body.track_position,
                "seek_position": body.seek_position,
            },
        )
        party_schema = await _commit_and_build_party_schema(session, party, int(user["id"]))

    await _notify_party_state(
        code,
        "playback_sync",
        {
            "action": body.action,
            "track_position": body.track_position,
            "seek_position": body.seek_position,
            "updated_by": user["id"],
        },
    )
    return party_schema


@app.post("/api/party/{code}/close")
async def close_party(code: str, user: dict = Depends(get_current_user)):
    """Close party session (creator only)."""
    async with async_session() as session:
        party = await _get_party_or_404(session, code)
        if party.creator_id != user["id"]:
            raise HTTPException(status_code=403, detail="Only DJ can close")

        party.is_active = False
        await _record_party_event(
            session,
            party.id,
            "closed",
            f"{user.get('first_name', 'DJ')} завершил(а) пати",
            actor_id=user["id"],
            actor_name=user.get("first_name", "DJ"),
        )
        await session.commit()

    await _notify_party_state(code, "closed", {})
    # Clean up subscribers
    _party_subscribers.pop(code, None)
    return {"ok": True}


@app.post("/api/party/{code}/save-playlist", response_model=PlaylistSchema)
async def save_party_as_playlist(code: str, user: dict = Depends(get_current_user)):
    """Save current party queue as a regular playlist for the requesting user."""
    from sqlalchemy import func, select

    from bot.db import upsert_track
    from bot.models.playlist import Playlist, PlaylistTrack

    await _get_or_create_webapp_user(user)
    async with async_session() as session:
        party = await _get_party_or_404(session, code)
        tracks = (
            await session.execute(
                select(PartyTrack)
                .where(PartyTrack.party_id == party.id)
                .order_by(PartyTrack.position, PartyTrack.id)
            )
        ).scalars().all()
        if not tracks:
            raise HTTPException(status_code=400, detail="Party queue is empty")

        playlist = Playlist(user_id=user["id"], name=f"Party • {party.name}"[:100])
        session.add(playlist)
        await session.flush()

        for idx, track in enumerate(tracks):
            db_track = await upsert_track(
                source_id=track.video_id,
                source=track.source,
                title=track.title,
                artist=track.artist,
                duration=track.duration,
                cover_url=track.cover_url,
            )
            session.add(PlaylistTrack(playlist_id=playlist.id, track_id=db_track.id, position=idx))

        await _record_party_event(
            session,
            party.id,
            "playlist_saved",
            f"{user.get('first_name', 'User')} сохранил(а) пати как плейлист",
            actor_id=user["id"],
            actor_name=user.get("first_name", "User"),
            payload={"playlist_name": playlist.name},
        )
        await session.commit()

        cnt = (
            await session.execute(
                select(func.count(PlaylistTrack.id)).where(PlaylistTrack.playlist_id == playlist.id)
            )
        ).scalar() or 0

    await _notify_party_state(code, "playlist_saved", {"playlist_name": f"Party • {party.name}"[:100]})
    return PlaylistSchema(id=playlist.id, name=playlist.name, track_count=cnt)


@app.post("/api/party/{code}/chat", response_model=PartySchema)
async def send_party_chat_message(code: str, body: PartyChatRequest, user: dict = Depends(get_current_user)):
    """Send a live chat message to the party room."""
    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")
    async with async_session() as session:
        party = await _get_party_or_404(session, code)
        await _ensure_party_member(session, party, user, mark_online=False)
        session.add(
            PartyChatMessage(
                party_id=party.id,
                user_id=user["id"],
                display_name=user.get("first_name", "User"),
                message=message[:400],
            )
        )
        await _record_party_event(
            session,
            party.id,
            "chat",
            f"{user.get('first_name', 'User')}: {message[:180]}",
            actor_id=user["id"],
            actor_name=user.get("first_name", "User"),
            payload={"message": message[:400]},
        )
        party_schema = await _commit_and_build_party_schema(session, party, int(user["id"]))

    await _notify_party_state(code, "chat", {"message": message[:400], "actor_name": user.get("first_name", "User")})
    return party_schema


@app.delete("/api/party/{code}/chat/{message_id}", response_model=PartySchema)
async def delete_party_chat_message(code: str, message_id: int, user: dict = Depends(get_current_user)):
    """Delete one chat message from the party room."""
    async with async_session() as session:
        from sqlalchemy import select

        party = await _get_party_or_404(session, code)
        member = await _ensure_party_member(session, party, user, mark_online=False)
        message = (
            await session.execute(
                select(PartyChatMessage).where(
                    PartyChatMessage.party_id == party.id,
                    PartyChatMessage.id == message_id,
                )
            )
        ).scalar_one_or_none()
        if message is None:
            raise HTTPException(status_code=404, detail="Chat message not found")
        can_moderate = member.role in {"dj", "cohost"} or party.creator_id == user["id"]
        if not can_moderate and message.user_id != user["id"]:
            raise HTTPException(status_code=403, detail="Not allowed to delete this message")

        deleted_preview = message.message[:120]
        await session.delete(message)
        await _record_party_event(
            session,
            party.id,
            "chat_delete",
            f"{user.get('first_name', 'User')} удалил(а) сообщение из чата",
            actor_id=user["id"],
            actor_name=user.get("first_name", "User"),
            payload={"message_id": message_id, "preview": deleted_preview},
        )
        party_schema = await _commit_and_build_party_schema(session, party, int(user["id"]))

    await _notify_party_state(code, "chat_delete", {"message_id": message_id})
    return party_schema


@app.post("/api/party/{code}/chat/clear", response_model=PartySchema)
async def clear_party_chat(code: str, user: dict = Depends(get_current_user)):
    """Clear party chat history for moderators."""
    async with async_session() as session:
        party = await _get_party_or_404(session, code)
        member = await _ensure_party_member(session, party, user, mark_online=False)
        if member.role not in {"dj", "cohost"} and party.creator_id != user["id"]:
            raise HTTPException(status_code=403, detail="Only DJ/co-host can clear chat")

        await session.execute(
            PartyChatMessage.__table__.delete().where(PartyChatMessage.party_id == party.id)
        )
        await _record_party_event(
            session,
            party.id,
            "chat_clear",
            f"{user.get('first_name', 'User')} очистил(а) чат",
            actor_id=user["id"],
            actor_name=user.get("first_name", "User"),
        )
        party_schema = await _commit_and_build_party_schema(session, party, int(user["id"]))

    await _notify_party_state(code, "chat_clear", {})
    return party_schema


@app.post("/api/party/{code}/react", response_model=PartySchema)
async def react_to_party_track(code: str, body: PartyReactionRequest, user: dict = Depends(get_current_user)):
    """Add a live emoji reaction to the current party track."""
    emoji = (body.emoji or "🔥")[:8]
    async with async_session() as session:
        from sqlalchemy import select

        party = await _get_party_or_404(session, code)
        await _ensure_party_member(session, party, user, mark_online=False)
        current_track = (
            await session.execute(
                select(PartyTrack).where(
                    PartyTrack.party_id == party.id,
                    PartyTrack.position == party.current_position,
                )
            )
        ).scalar_one_or_none()
        if current_track is None:
            raise HTTPException(status_code=400, detail="No active track")

        existing = (
            await session.execute(
                select(PartyReaction).where(
                    PartyReaction.track_id == current_track.id,
                    PartyReaction.user_id == user["id"],
                    PartyReaction.emoji == emoji,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                PartyReaction(
                    party_id=party.id,
                    track_id=current_track.id,
                    user_id=user["id"],
                    emoji=emoji,
                )
            )
            await _record_party_event(
                session,
                party.id,
                "reaction",
                f"{user.get('first_name', 'User')} отреагировал(а) {emoji}",
                actor_id=user["id"],
                actor_name=user.get("first_name", "User"),
                payload={"emoji": emoji, "video_id": current_track.video_id},
            )
            party_schema = await _commit_and_build_party_schema(session, party, int(user["id"]))
        else:
            party_schema = await _build_party_schema(session, party, int(user["id"]))

    await _notify_party_state(code, "reaction", {"emoji": emoji, "user_id": user["id"]})
    return party_schema


@app.post("/api/party/{code}/auto-dj", response_model=PartySchema)
async def auto_dj_fill_party(code: str, limit: int = Query(default=5, ge=1, le=10), user: dict = Depends(get_current_user)):
    """Auto-fill the party queue with AI recommendations based on the room vibe."""
    async with async_session() as session:
        from sqlalchemy import func, select

        party = await _get_party_or_404(session, code)
        member = await _ensure_party_member(session, party, user, mark_online=False)
        if member.role not in {"dj", "cohost"} and party.creator_id != user["id"]:
            raise HTTPException(status_code=403, detail="Only DJ/co-host can run Auto-DJ")

        tracks = (
            await session.execute(
                select(PartyTrack)
                .where(PartyTrack.party_id == party.id)
                .order_by(PartyTrack.position.desc())
            )
        ).scalars().all()
        existing_ids = {t.video_id for t in tracks}
        seed_track = next((t for t in tracks if t.position == party.current_position), None) or (tracks[0] if tracks else None)

        suggestions: list[TrackSchema] = []
        if seed_track is not None and settings.SUPABASE_AI_ENABLED:
            suggestions = (await get_similar(seed_track.video_id, limit=limit * 2, user=user)).tracks
        if not suggestions:
            suggestions = (await get_wave(int(user["id"]), limit=limit * 2, mood=None, user=user)).tracks
        if not suggestions and seed_track is not None:
            from bot.services.downloader import search_tracks

            raw_results = await search_tracks(f"{seed_track.artist} similar", max_results=limit * 2, source="youtube")
            suggestions = [
                TrackSchema(
                    video_id=r.get("video_id", ""),
                    title=r.get("title", "Unknown"),
                    artist=r.get("artist", r.get("uploader", "Unknown")),
                    duration=r.get("duration", 0),
                    duration_fmt=r.get("duration_fmt", "0:00"),
                    source=r.get("source", "youtube"),
                    cover_url=r.get("cover_url"),
                )
                for r in raw_results
                if r.get("video_id")
            ]

        max_pos = (await session.execute(select(func.coalesce(func.max(PartyTrack.position), -1)).where(PartyTrack.party_id == party.id))).scalar() or -1
        added = 0
        for suggestion in suggestions:
            if suggestion.video_id in existing_ids:
                continue
            max_pos += 1
            session.add(
                PartyTrack(
                    party_id=party.id,
                    video_id=suggestion.video_id,
                    title=suggestion.title,
                    artist=suggestion.artist,
                    duration=suggestion.duration,
                    duration_fmt=suggestion.duration_fmt,
                    source=suggestion.source,
                    cover_url=suggestion.cover_url,
                    added_by=user["id"],
                    added_by_name="AI Auto-DJ",
                    position=max_pos,
                )
            )
            existing_ids.add(suggestion.video_id)
            added += 1
            if added >= limit:
                break

        if added == 0:
            raise HTTPException(status_code=400, detail="Auto-DJ found no new tracks")

        await _record_party_event(
            session,
            party.id,
            "auto_dj",
            f"{user.get('first_name', 'DJ')} включил(а) AI Auto-DJ (+{added} треков)",
            actor_id=user["id"],
            actor_name=user.get("first_name", "DJ"),
            payload={"added": added},
        )
        party_schema = await _commit_and_build_party_schema(session, party, int(user["id"]))

    await _notify_party_state(code, "auto_dj", {"added": added})
    return party_schema


@app.get("/api/party/{code}/recap", response_model=PartyRecapSchema)
async def get_party_recap(code: str, user: dict = Depends(get_current_user)):
    """Return summary stats for a party session."""
    async with async_session() as session:
        from collections import Counter
        from sqlalchemy import func, select

        party = await _get_party_or_404(session, code)
        await _ensure_party_member(session, party, user, mark_online=False)
        tracks = (
            await session.execute(
                select(PartyTrack).where(PartyTrack.party_id == party.id)
            )
        ).scalars().all()
        members = (
            await session.execute(
                select(PartyMember).where(PartyMember.party_id == party.id)
            )
        ).scalars().all()
        events_count = (
            await session.execute(select(func.count(PartyEvent.id)).where(PartyEvent.party_id == party.id))
        ).scalar() or 0
        skip_votes = (
            await session.execute(select(func.count(PartyTrackVote.id)).where(PartyTrackVote.party_id == party.id, PartyTrackVote.vote_type == "skip"))
        ).scalar() or 0

        contributor_counter = Counter(t.added_by_name or "Unknown" for t in tracks)
        artist_counter = Counter(t.artist or "Unknown" for t in tracks)
        total_duration = sum(t.duration or 0 for t in tracks)

        return PartyRecapSchema(
            total_tracks=len(tracks),
            total_members=len(members),
            online_members=sum(1 for m in members if m.is_online),
            total_duration=total_duration,
            total_skip_votes=skip_votes,
            events_count=events_count,
            top_contributors=[PartyRecapStatSchema(label=label, value=value) for label, value in contributor_counter.most_common(3)],
            top_artists=[PartyRecapStatSchema(label=label, value=value) for label, value in artist_counter.most_common(3)],
        )


@app.get("/api/party/{code}/events")
async def party_events(
    code: str,
    request: Request,
    x_telegram_init_data: str | None = Header(None),
    token: str | None = Query(None),
):
    """SSE stream for real-time party updates."""
    # Auth: accept header or query param (EventSource can't send headers)
    init_data = x_telegram_init_data or token
    if not init_data:
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = verify_init_data(init_data)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid initData")
    await _get_or_create_webapp_user(user)
    # Verify party exists
    async with async_session() as session:
        party = await _get_party_or_404(session, code)
        member = await _ensure_party_member(session, party, user, mark_online=True)
        joined_message = None
        if member.display_name:
            joined_message = f"{member.display_name} присоединился(ась) к пати"
        await _record_party_event(
            session,
            party.id,
            "member_joined",
            joined_message or "Новый участник вошёл в комнату",
            actor_id=user["id"],
            actor_name=user.get("first_name", "User"),
            payload={"user_id": user["id"]},
        )
        await session.commit()

    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=50)
    if code not in _party_subscribers:
        _party_subscribers[code] = []
    _party_subscribers[code].append(queue)

    # Notify others that someone joined
    await _notify_party_state(code, "member_joined", {
        "user_id": user["id"],
        "name": user.get("first_name", "User"),
        "member_count": len(_party_subscribers.get(code, [])),
    })

    async def event_generator():
        try:
            yield f"data: {json.dumps({'event': 'connected'})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            subs = _party_subscribers.get(code, [])
            try:
                subs.remove(queue)
            except ValueError:
                pass
            try:
                async with async_session() as session:
                    from sqlalchemy import select

                    result = await session.execute(
                        select(PartySession).where(PartySession.invite_code == code)
                    )
                    party = result.scalar_one_or_none()
                    if party is not None:
                        member = (
                            await session.execute(
                                select(PartyMember).where(
                                    PartyMember.party_id == party.id,
                                    PartyMember.user_id == user["id"],
                                )
                            )
                        ).scalar_one_or_none()
                        if member is not None:
                            member.is_online = False
                            member.last_seen_at = datetime.now(timezone.utc)
                        await _record_party_event(
                            session,
                            party.id,
                            "member_left",
                            f"{user.get('first_name', 'User')} вышел(шла) из комнаты",
                            actor_id=user["id"],
                            actor_name=user.get("first_name", "User"),
                            payload={"user_id": user["id"]},
                        )
                        await session.commit()
            except Exception:
                pass
            # Notify others that someone left
            await _notify_party_state(code, "member_left", {
                "member_count": len(_party_subscribers.get(code, [])),
            })

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/my-parties", response_model=list[PartySchema])
async def my_parties(user: dict = Depends(get_current_user)):
    """List user's active parties."""
    async with async_session() as session:
        from sqlalchemy import func, select

        result = await session.execute(
            select(PartySession).where(
                PartySession.creator_id == user["id"],
                PartySession.is_active == True,
            ).order_by(PartySession.created_at.desc())
        )
        parties = result.scalars().all()
        if not parties:
            return []

        party_ids = [party.id for party in parties]
        track_rows = await session.execute(
            select(PartyTrack.party_id, func.count(PartyTrack.id))
            .where(PartyTrack.party_id.in_(party_ids))
            .group_by(PartyTrack.party_id)
        )
        track_counts = {party_id: count for party_id, count in track_rows.all()}

        member_rows = await session.execute(
            select(PartyMember.party_id, func.count(PartyMember.id))
            .where(
                PartyMember.party_id.in_(party_ids),
                PartyMember.is_online == True,
            )
            .group_by(PartyMember.party_id)
        )
        online_counts = {party_id: count for party_id, count in member_rows.all()}

        return [
            PartySchema(
                id=party.id,
                invite_code=party.invite_code,
                creator_id=party.creator_id,
                name=party.name,
                is_active=party.is_active,
                current_position=party.current_position,
                track_count=int(track_counts.get(party.id, 0)),
                tracks=[],
                member_count=int(online_counts.get(party.id, 0)),
                skip_threshold=_party_skip_threshold(int(online_counts.get(party.id, 0))),
                viewer_role="dj",
                members=[],
                events=[],
                chat_messages=[],
                playback=PartyPlaybackStateSchema(),
                current_reactions={},
            )
            for party in parties
        ]


# ── Radio Mode (infinite autoplay) ─────────────────────────────────────

@app.post("/api/radio/next")
async def radio_next(
    request: Request,
    user: dict = Depends(get_current_user),
):
    """
    Get next batch of radio tracks based on seed track.
    Uses similar tracks + trending mix for variety.
    """
    body = await request.json()
    seed_id = body.get("seed_video_id", "")
    exclude = body.get("exclude", [])
    limit = min(body.get("limit", 8), 20)

    if not seed_id:
        raise HTTPException(400, "seed_video_id required")

    tracks = []
    try:
        # Try similar tracks first
        from bot.services.search_engine import search as _search
        from bot.services.downloader import resolve_youtube_url

        # Get track info for search
        from bot.models.base import async_session as _as
        from bot.models.track import Track as TrackModel
        from sqlalchemy import select

        seed_title = ""
        seed_artist = ""
        async with _as() as session:
            t = (await session.execute(
                select(TrackModel).where(TrackModel.source_id == seed_id)
            )).scalar_one_or_none()
            if t:
                seed_title = t.title or ""
                seed_artist = t.artist or ""

        # Mix strategy: similar + artist radio + random trending
        queries = []
        if seed_artist:
            queries.append(f"{seed_artist} mix")
            queries.append(f"{seed_artist} best songs")
        if seed_title and seed_artist:
            queries.append(f"{seed_title} {seed_artist} similar")

        exclude_set = set(exclude + [seed_id])
        seen = set()

        for q in queries[:3]:
            try:
                results = await asyncio.wait_for(
                    asyncio.get_running_loop().run_in_executor(
                        None, lambda qq=q: _search(qq, max_results=8)
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
                        if len(tracks) >= limit:
                            break
            except Exception:
                continue
            if len(tracks) >= limit:
                break

    except Exception as e:
        logger.error("Radio next failed: %s", e)

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
                return {"error": "User not found"}

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
            top_tracks = [{
                "video_id": r[0], "title": r[1], "artist": r[2], "cover_url": r[3],
                "duration": r[4] or 0, "duration_fmt": f"{(r[4] or 0)//60}:{(r[4] or 0)%60:02d}",
                "play_count": r[5], "source": "db",
            } for r in top_tracks_q.all()]

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
        return {"error": "timeout", "total_plays": 0}
    except Exception as e:
        logger.error("Wrapped failed: %s", e)
        return {"error": str(e), "total_plays": 0}


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


# ── Live Radio Broadcast (DJ-controlled stream) ───────────────────────

_broadcast_subscribers: list[asyncio.Queue] = []

_BCAST_LIVE_KEY = "broadcast:live"
_BCAST_STATE_KEY = "broadcast:state"
_BCAST_QUEUE_KEY = "broadcast:queue"


_BROADCAST_DJ_USERNAMES = {"tequilasunshine1", "kg_1988hp"}


def _is_broadcast_dj(user: dict) -> bool:
    """Check if user is an authorized broadcast DJ."""
    username = (user.get("username") or "").lower()
    return username in _BROADCAST_DJ_USERNAMES


async def _require_broadcast_admin(user: dict):
    if not _is_broadcast_dj(user):
        raise HTTPException(status_code=403, detail="Only authorized DJs can control the broadcast")


async def _notify_broadcast(event: str, data: dict | None = None):
    """Send SSE event to all broadcast listeners."""
    payload = json.dumps({"event": event, "data": data or {}}, ensure_ascii=False)
    dead: list[asyncio.Queue] = []
    for q in _broadcast_subscribers:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        try:
            _broadcast_subscribers.remove(q)
        except ValueError:
            pass


async def _get_broadcast_state() -> dict:
    """Read broadcast state from Redis."""
    r = await _get_redis()
    is_live = await r.get(_BCAST_LIVE_KEY)
    if not is_live:
        return {
            "is_live": False, "dj_id": None, "dj_name": None,
            "current_idx": 0, "seek_pos": 0, "action": "idle",
            "started_at": None, "updated_at": None, "channel": None,
            "listener_count": len(_broadcast_subscribers), "tracks": [],
        }

    state = await r.hgetall(_BCAST_STATE_KEY)
    queue_raw = await r.lrange(_BCAST_QUEUE_KEY, 0, -1)
    tracks = []
    for i, raw in enumerate(queue_raw):
        try:
            t = json.loads(raw)
            t["position"] = i
            tracks.append(t)
        except Exception:
            pass

    return {
        "is_live": True,
        "dj_id": int(state.get("dj_id", 0)) if state.get("dj_id") else None,
        "dj_name": state.get("dj_name"),
        "current_idx": int(state.get("current_idx", 0)),
        "seek_pos": float(state.get("seek_pos", 0)),
        "action": state.get("action", "idle"),
        "started_at": state.get("started_at"),
        "updated_at": state.get("updated_at"),
        "channel": state.get("channel"),
        "listener_count": len(_broadcast_subscribers),
        "tracks": tracks,
    }


_BCAST_PIN_KEY = "broadcast:pinned_msgs"  # Redis hash: group_id -> message_id


async def _broadcast_notify_chat(action: str, dj_name: str = "DJ"):
    """Send broadcast notification to Telegram group chat. Pin ON AIR, unpin on stop."""
    try:
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

        if not settings.BLACKROOM_GROUP_ID or not settings.BOT_TOKEN:
            return

        bot = Bot(
            token=settings.BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        try:
            r = await _get_redis()

            group_ids = [
                int(gid.strip())
                for gid in str(settings.BLACKROOM_GROUP_ID).split(",")
                if gid.strip()
            ]

            if action == "started":
                text = (
                    f"<b>ON AIR</b>\n\n"
                    f"DJ <b>{dj_name}</b> started a live broadcast!\n"
                    f"Open the app to listen together"
                )
                rows = []
                if settings.TMA_URL:
                    broadcast_url = f"{settings.TMA_URL.rstrip('/')}?startapp=broadcast"
                    rows.append([
                        InlineKeyboardButton(
                            text="Listen Live",
                            web_app=WebAppInfo(url=broadcast_url),
                        ),
                    ])
                kb = InlineKeyboardMarkup(inline_keyboard=rows) if rows else None

                for gid in group_ids:
                    try:
                        msg = await bot.send_message(gid, text, reply_markup=kb)
                        try:
                            await bot.pin_chat_message(
                                chat_id=gid,
                                message_id=msg.message_id,
                                disable_notification=False,
                            )
                            await r.hset(_BCAST_PIN_KEY, str(gid), str(msg.message_id))
                        except Exception as pin_err:
                            logger.warning("Failed to pin ON AIR in %s: %s", gid, pin_err)
                    except Exception as e:
                        logger.warning("Failed to notify group %s: %s", gid, e)

            elif action == "stopped":
                for gid in group_ids:
                    try:
                        pinned_mid = await r.hget(_BCAST_PIN_KEY, str(gid))
                        if pinned_mid:
                            mid = int(pinned_mid)
                            try:
                                await bot.unpin_chat_message(chat_id=gid, message_id=mid)
                            except Exception:
                                pass
                            try:
                                await bot.delete_message(chat_id=gid, message_id=mid)
                            except Exception:
                                pass
                            await r.hdel(_BCAST_PIN_KEY, str(gid))
                    except Exception:
                        pass

                text = "The broadcast has ended. See you next time!"
                for gid in group_ids:
                    try:
                        await bot.send_message(gid, text)
                    except Exception as e:
                        logger.warning("Failed to notify group %s: %s", gid, e)
        finally:
            await bot.session.close()
    except Exception as e:
        logger.error("Broadcast chat notification failed: %s", e)


async def _broadcast_sync_voice_chat(r, action: str, channel: str = "tequila"):
    """Sync broadcast queue to voice chat Redis queue for the streamer."""
    try:
        vc_queue_key = "radio:queue:broadcast"

        if action == "started":
            # Copy current broadcast queue to voice chat queue
            queue_raw = await r.lrange(_BCAST_QUEUE_KEY, 0, -1)
            if queue_raw:
                await r.delete(vc_queue_key)
                for raw in queue_raw:
                    await r.rpush(vc_queue_key, raw)
                logger.info("Synced %d tracks to voice chat queue", len(queue_raw))

        elif action == "stopped":
            await r.delete(vc_queue_key)
            await r.delete("radio:current:broadcast")

        elif action == "next":
            # Push the next track to voice chat queue
            state = await r.hgetall(_BCAST_STATE_KEY)
            current_idx = int(state.get("current_idx", 0))
            track_raw = await r.lindex(_BCAST_QUEUE_KEY, current_idx)
            if track_raw:
                await r.rpush(vc_queue_key, track_raw)
    except Exception as e:
        logger.error("Voice chat sync failed: %s", e)


@app.get("/api/broadcast")
async def get_broadcast(user: dict = Depends(get_current_user)):
    """Get current broadcast state + queue."""
    state = await _get_broadcast_state()
    state["is_dj"] = _is_broadcast_dj(user)
    return state


@app.post("/api/broadcast/start")
async def start_broadcast(request: Request, user: dict = Depends(get_current_user)):
    """Start a live broadcast. Admin only."""
    await _require_broadcast_admin(user)
    r = await _get_redis()

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    channel = body.get("channel", "tequila")
    limit = min(int(body.get("limit", 30)), 100)

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    await r.set(_BCAST_LIVE_KEY, "1")
    await r.hset(_BCAST_STATE_KEY, mapping={
        "dj_id": str(user["id"]),
        "dj_name": user.get("first_name", "DJ"),
        "action": "idle",
        "current_idx": "0",
        "seek_pos": "0",
        "started_at": now,
        "updated_at": now,
        "channel": channel,
    })
    # Clear old queue
    await r.delete(_BCAST_QUEUE_KEY)

    # Load tracks from channel
    try:
        await _load_channel_to_broadcast(r, channel, limit)
    except Exception as e:
        logger.error("Failed to load channel tracks for broadcast: %s", e)

    await _notify_broadcast("started", {
        "dj_id": user["id"], "dj_name": user.get("first_name", "DJ"),
    })

    # Notify Telegram group chat + sync voice chat
    dj_name = user.get("first_name", "DJ")
    _fire_task(_broadcast_notify_chat("started", dj_name))
    _fire_task(_broadcast_sync_voice_chat(r, "started", channel))

    return await _get_broadcast_state()


async def _load_channel_to_broadcast(r, channel: str, limit: int, exclude: list[str] | None = None):
    """Load tracks from DB channel into broadcast queue."""
    from bot.models.base import async_session as _as
    from bot.models.track import Track as TrackModel
    from sqlalchemy import select, func

    exclude_set = set(exclude or [])

    async with _as() as session:
        q = select(
            TrackModel.source_id, TrackModel.title, TrackModel.artist,
            TrackModel.duration, TrackModel.cover_url, TrackModel.file_id,
        ).where(
            TrackModel.channel == channel,
            TrackModel.file_id.isnot(None),
        ).order_by(func.random()).limit(limit)

        result = await session.execute(q)
        for row in result.all():
            vid = row[0]
            if vid in exclude_set:
                continue
            track_data = json.dumps({
                "video_id": vid,
                "title": row[1] or "Unknown",
                "artist": row[2] or "Unknown",
                "duration": row[3] or 0,
                "duration_fmt": f"{(row[3] or 0) // 60}:{(row[3] or 0) % 60:02d}",
                "source": "channel",
                "cover_url": row[4],
                "file_id": row[5],
                "channel": channel,
            }, ensure_ascii=False)
            await r.rpush(_BCAST_QUEUE_KEY, track_data)


@app.get("/api/broadcast/channels")
async def broadcast_channels(user: dict = Depends(get_current_user)):
    """List available channel labels with track counts."""
    await _require_broadcast_admin(user)
    from bot.models.base import async_session as _as
    from bot.models.track import Track as TrackModel
    from sqlalchemy import select, func

    async with _as() as session:
        result = await session.execute(
            select(TrackModel.channel, func.count())
            .where(TrackModel.channel.isnot(None), TrackModel.file_id.isnot(None))
            .group_by(TrackModel.channel)
            .order_by(func.count().desc())
        )
        channels = [{"label": r[0], "track_count": r[1]} for r in result.all()]
    return {"channels": channels}


@app.post("/api/broadcast/import-channel")
async def broadcast_import_channel(request: Request, user: dict = Depends(get_current_user)):
    """
    Import audio tracks from a Telegram channel into DB.
    DJ enters @channel_username, backend scans it via Bot API.
    """
    await _require_broadcast_admin(user)
    body = await request.json()
    channel_ref = body.get("channel_ref", "").strip()
    label = body.get("label", "").strip().lower() or channel_ref.lstrip("@").lower()

    if not channel_ref:
        raise HTTPException(400, "channel_ref required (e.g. @my_music_channel)")
    if len(channel_ref) > 128:
        raise HTTPException(400, "channel_ref too long")
    import re as _re
    if not _re.match(r'^@?[a-zA-Z0-9_]+$', channel_ref):
        raise HTTPException(400, "Invalid channel_ref format")

    # Import in background so the request doesn't timeout
    _fire_task(_import_channel_tracks(user, channel_ref, label))
    return {"status": "importing", "channel": channel_ref, "label": label}


async def _import_channel_tracks(user: dict, channel_ref: str, label: str):
    """Background task: scan a Telegram channel and import audio to DB."""
    import time as _time
    try:
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode
        from bot.db import upsert_track

        bot = Bot(
            token=settings.BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        admin_id = int(user["id"])
        try:
            chat = await bot.get_chat(channel_ref)
            chat_id = chat.id
            saved, msg_id, consecutive_fails = 0, 0, 0
            start_time = _time.monotonic()
            max_scan = 5000  # Max messages to scan
            timeout_sec = 300  # 5 min limit

            while consecutive_fails < 30 and msg_id < max_scan:
                if _time.monotonic() - start_time > timeout_sec:
                    logger.warning("Channel import timeout for %s after %d msgs", channel_ref, msg_id)
                    break
                msg_id += 1
                try:
                    fwd = await bot.forward_message(
                        chat_id=admin_id,
                        from_chat_id=chat_id,
                        message_id=msg_id,
                        disable_notification=True,
                    )
                    consecutive_fails = 0

                    if fwd.audio:
                        audio = fwd.audio
                        source_id = f"tg_{chat_id}_{msg_id}"
                        title = audio.title or (audio.file_name or "Unknown")
                        artist = audio.performer or ""

                        await upsert_track(
                            source_id=source_id,
                            title=title,
                            artist=artist,
                            duration=audio.duration,
                            file_id=audio.file_id,
                            source="channel",
                            channel=label,
                        )
                        saved += 1

                    try:
                        await bot.delete_message(admin_id, fwd.message_id)
                    except Exception:
                        pass

                    await asyncio.sleep(0.1)
                except Exception:
                    consecutive_fails += 1
                    await asyncio.sleep(0.05)

            logger.info("Imported %d tracks from %s -> %s", saved, channel_ref, label)

            try:
                await bot.send_message(
                    admin_id,
                    f"Import done! {saved} tracks from {channel_ref} -> {label}",
                )
            except Exception:
                pass
        finally:
            await bot.session.close()
    except Exception as e:
        logger.error("Channel import failed: %s", e)


@app.post("/api/broadcast/stop")
async def stop_broadcast(user: dict = Depends(get_current_user)):
    """Stop the broadcast. Admin only."""
    await _require_broadcast_admin(user)
    r = await _get_redis()
    await r.delete(_BCAST_LIVE_KEY, _BCAST_STATE_KEY, _BCAST_QUEUE_KEY)
    await _notify_broadcast("stopped", {})

    # Notify chat + stop voice chat
    _fire_task(_broadcast_notify_chat("stopped"))
    _fire_task(_broadcast_sync_voice_chat(r, "stopped"))

    return {"ok": True}


@app.post("/api/broadcast/load-channel")
async def broadcast_load_channel(request: Request, user: dict = Depends(get_current_user)):
    """Load tracks from a Telegram channel into broadcast queue. Admin only."""
    await _require_broadcast_admin(user)
    body = await request.json()
    channel = body.get("channel", "tequila")
    limit = min(int(body.get("limit", 30)), 100)

    r = await _get_redis()
    is_live = await r.get(_BCAST_LIVE_KEY)
    if not is_live:
        raise HTTPException(400, "Broadcast not active")

    # Get existing queue video_ids to avoid duplicates
    existing = await r.lrange(_BCAST_QUEUE_KEY, 0, -1)
    exclude = []
    for raw in existing:
        try:
            exclude.append(json.loads(raw).get("video_id", ""))
        except Exception:
            pass

    await _load_channel_to_broadcast(r, channel, limit, exclude)
    await _notify_broadcast("queue_updated", {
        "track_count": await r.llen(_BCAST_QUEUE_KEY),
    })
    return await _get_broadcast_state()


@app.post("/api/broadcast/tracks")
async def broadcast_add_track(request: Request, user: dict = Depends(get_current_user)):
    """Add a single track to broadcast queue. Admin only."""
    await _require_broadcast_admin(user)
    body = await request.json()
    r = await _get_redis()

    is_live = await r.get(_BCAST_LIVE_KEY)
    if not is_live:
        raise HTTPException(400, "Broadcast not active")

    track_data = json.dumps({
        "video_id": body.get("video_id", ""),
        "title": body.get("title", ""),
        "artist": body.get("artist", ""),
        "duration": body.get("duration", 0),
        "duration_fmt": body.get("duration_fmt", "0:00"),
        "source": body.get("source", "youtube"),
        "cover_url": body.get("cover_url"),
    }, ensure_ascii=False)
    await r.rpush(_BCAST_QUEUE_KEY, track_data)

    await _notify_broadcast("queue_updated", {
        "track_count": await r.llen(_BCAST_QUEUE_KEY),
    })
    return await _get_broadcast_state()


@app.delete("/api/broadcast/tracks/{video_id}")
async def broadcast_remove_track(video_id: str, user: dict = Depends(get_current_user)):
    """Remove a track from broadcast queue. Admin only."""
    await _require_broadcast_admin(user)
    r = await _get_redis()

    queue_raw = await r.lrange(_BCAST_QUEUE_KEY, 0, -1)
    for raw in queue_raw:
        try:
            t = json.loads(raw)
            if t.get("video_id") == video_id:
                await r.lrem(_BCAST_QUEUE_KEY, 1, raw)
                break
        except Exception:
            pass

    await _notify_broadcast("queue_updated", {
        "track_count": await r.llen(_BCAST_QUEUE_KEY),
    })
    return {"ok": True}


@app.post("/api/broadcast/reorder")
async def broadcast_reorder(request: Request, user: dict = Depends(get_current_user)):
    """Reorder tracks in broadcast queue. Admin only."""
    await _require_broadcast_admin(user)
    body = await request.json()
    from_pos = int(body.get("from_position", 0))
    to_pos = int(body.get("to_position", 0))

    r = await _get_redis()
    queue_raw = await r.lrange(_BCAST_QUEUE_KEY, 0, -1)
    if from_pos < 0 or from_pos >= len(queue_raw) or to_pos < 0 or to_pos >= len(queue_raw):
        raise HTTPException(400, "Invalid positions")

    items = list(queue_raw)
    item = items.pop(from_pos)
    items.insert(to_pos, item)

    pipe = r.pipeline()
    pipe.delete(_BCAST_QUEUE_KEY)
    for it in items:
        pipe.rpush(_BCAST_QUEUE_KEY, it)
    await pipe.execute()

    await _notify_broadcast("queue_updated", {
        "track_count": len(items),
    })
    return await _get_broadcast_state()


@app.post("/api/broadcast/skip")
async def broadcast_skip(user: dict = Depends(get_current_user)):
    """Skip to next track. Admin only."""
    await _require_broadcast_admin(user)
    r = await _get_redis()

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    current_idx = int(await r.hget(_BCAST_STATE_KEY, "current_idx") or 0)
    queue_len = await r.llen(_BCAST_QUEUE_KEY)
    new_idx = min(current_idx + 1, max(queue_len - 1, 0))

    await r.hset(_BCAST_STATE_KEY, mapping={
        "current_idx": str(new_idx),
        "seek_pos": "0",
        "action": "play",
        "updated_at": now,
    })

    # Get new track info
    track_raw = await r.lindex(_BCAST_QUEUE_KEY, new_idx)
    track = json.loads(track_raw) if track_raw else {}

    await _notify_broadcast("next", {
        "position": new_idx,
        "track": track,
    })
    return await _get_broadcast_state()


@app.post("/api/broadcast/playback")
async def broadcast_playback(request: Request, user: dict = Depends(get_current_user)):
    """Sync playback state (play/pause/seek). Admin only."""
    await _require_broadcast_admin(user)
    body = await request.json()
    action = body.get("action", "play")
    seek_pos = float(body.get("seek_pos", 0))

    r = await _get_redis()
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    mapping = {"action": action, "updated_at": now}
    if seek_pos > 0:
        mapping["seek_pos"] = str(seek_pos)
    if "current_idx" in body:
        mapping["current_idx"] = str(int(body["current_idx"]))

    await r.hset(_BCAST_STATE_KEY, mapping=mapping)

    await _notify_broadcast("playback_sync", {
        "action": action,
        "seek_pos": seek_pos,
        "current_idx": int(await r.hget(_BCAST_STATE_KEY, "current_idx") or 0),
    })
    return await _get_broadcast_state()


@app.post("/api/broadcast/advance")
async def broadcast_advance(user: dict = Depends(get_current_user)):
    """Auto-advance to next track (called by DJ client when track ends). Admin only."""
    await _require_broadcast_admin(user)
    r = await _get_redis()

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    current_idx = int(await r.hget(_BCAST_STATE_KEY, "current_idx") or 0)
    queue_len = await r.llen(_BCAST_QUEUE_KEY)
    new_idx = current_idx + 1

    # Auto-refill if running low
    if queue_len - new_idx < 5:
        channel = await r.hget(_BCAST_STATE_KEY, "channel") or "tequila"
        existing = await r.lrange(_BCAST_QUEUE_KEY, 0, -1)
        exclude = []
        for raw in existing:
            try:
                exclude.append(json.loads(raw).get("video_id", ""))
            except Exception:
                pass
        try:
            await _load_channel_to_broadcast(r, channel, 20, exclude)
        except Exception as e:
            logger.error("Broadcast auto-refill failed: %s", e)
        queue_len = await r.llen(_BCAST_QUEUE_KEY)

    # Wrap around if at end
    if new_idx >= queue_len:
        new_idx = 0

    await r.hset(_BCAST_STATE_KEY, mapping={
        "current_idx": str(new_idx),
        "seek_pos": "0",
        "action": "play",
        "updated_at": now,
    })

    track_raw = await r.lindex(_BCAST_QUEUE_KEY, new_idx)
    track = json.loads(track_raw) if track_raw else {}

    await _notify_broadcast("next", {
        "position": new_idx,
        "track": track,
    })

    # Sync next track to voice chat
    _fire_task(_broadcast_sync_voice_chat(r, "next"))

    return await _get_broadcast_state()


@app.get("/api/broadcast/events")
async def broadcast_events(
    request: Request,
    x_telegram_init_data: str | None = Header(None),
    token: str | None = Query(None),
):
    """SSE stream for real-time broadcast updates."""
    init_data = x_telegram_init_data or token
    if not init_data:
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = verify_init_data(init_data)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid initData")
    await _get_or_create_webapp_user(user)

    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=50)
    _broadcast_subscribers.append(queue)

    # Notify listener count update
    await _notify_broadcast("listener_count", {
        "count": len(_broadcast_subscribers),
    })

    async def event_generator():
        try:
            # Send initial state snapshot
            state = await _get_broadcast_state()
            yield f"data: {json.dumps({'event': 'connected', 'data': state}, ensure_ascii=False)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            try:
                _broadcast_subscribers.remove(queue)
            except ValueError:
                pass
            await _notify_broadcast("listener_count", {
                "count": len(_broadcast_subscribers),
            })

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
