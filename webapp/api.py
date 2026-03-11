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

# ── In-memory stream URL cache (avoids repeated yt-dlp resolves) ─────────
_stream_url_cache: dict[str, tuple[str, float]] = {}  # video_id -> (url, expires_at)
_STREAM_URL_TTL = 1800  # 30 minutes (YouTube URLs valid ~6h)
_stream_url_inflight: dict[str, asyncio.Future[str | None]] = {}
_stream_url_lock = asyncio.Lock()
_stream_url_resolve_semaphore = asyncio.Semaphore(1)
from webapp.auth import verify_init_data
from webapp.schemas import (
    LyricsResponse,
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

    # Periodic cleanup of expired stream URL cache entries
    async def _cleanup_url_cache():
        import time as _time
        while True:
            await asyncio.sleep(300)  # every 5 min
            now = _time.time()
            expired = [k for k, (_, exp) in _stream_url_cache.items() if exp < now]
            for k in expired:
                _stream_url_cache.pop(k, None)
            if expired:
                logger.debug("Cleaned %d expired stream URL cache entries", len(expired))

    cleanup_task = asyncio.create_task(_cleanup_url_cache())
    yield
    cleanup_task.cancel()
    await download_manager.shutdown()


# ── App ──────────────────────────────────────────────────────────────────

app = FastAPI(title="TMA Player", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Global exception handler ────────────────────────────────────────────

@app.middleware("http")
async def catch_exceptions_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:
        logger.error(
            "Unhandled %s %s → %s\n%s",
            request.method,
            request.url.path,
            exc,
            traceback.format_exc(),
        )
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
async def health():
    return {"status": "ok"}


async def _get_or_create_webapp_user(tg_user: dict):
    from datetime import datetime, timezone
    from sqlalchemy import select, update

    from bot.db import is_admin
    from bot.models.base import async_session
    from bot.models.user import User

    user_id = int(tg_user["id"])
    username = tg_user.get("username")
    first_name = tg_user.get("first_name") or ""
    admin = is_admin(user_id, username)
    now = datetime.now(timezone.utc)

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
            await session.commit()
            await session.refresh(db_user)
            return db_user

        update_values = {
            "username": username,
            "first_name": first_name,
            "last_active": now,
            "is_admin": admin,
        }
        expired_premium = (
            not admin
            and db_user.is_premium
            and db_user.premium_until is not None
            and db_user.premium_until < now
        )
        orphaned_premium = (
            not admin
            and db_user.is_premium
            and db_user.premium_until is None
        )
        if admin and not db_user.is_premium:
            update_values["is_premium"] = True
        if expired_premium or orphaned_premium:
            update_values["is_premium"] = False

        await session.execute(update(User).where(User.id == user_id).values(**update_values))
        await session.commit()

        for key, value in update_values.items():
            setattr(db_user, key, value)
        return db_user


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
    if not init_data or verify_init_data(init_data) is None:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Sanitize video_id to prevent path traversal
    import re
    if not re.match(r'^[a-zA-Z0-9_-]{1,64}$', video_id):
        raise HTTPException(status_code=400, detail="Invalid video_id")

    # Check if already downloaded (and valid size > 10KB)
    mp3_path = settings.DOWNLOAD_DIR / f"{video_id}.mp3"
    if mp3_path.exists() and mp3_path.stat().st_size < 10240:
        # Corrupt file, delete and re-download
        logger.warning("Removing corrupt file %s (size=%d)", mp3_path, mp3_path.stat().st_size)
        mp3_path.unlink()
    if not mp3_path.exists():
        try:
            # Determine source by prefix
            if video_id.startswith("ym_"):
                # Yandex Music track
                from bot.services.yandex_provider import download_yandex
                track_id = int(video_id[3:])  # Remove "ym_" prefix
                mp3_path = await download_yandex(track_id, mp3_path)
            elif video_id.startswith("sp_"):
                # Spotify track — search YouTube by metadata
                sp_query = await _spotify_id_to_query(video_id)
                if not sp_query:
                    raise HTTPException(status_code=404, detail="Spotify track not found")
                from bot.services.downloader import search_tracks
                results = await search_tracks(sp_query, max_results=1, source="youtube")
                if not results:
                    raise HTTPException(status_code=404, detail="No YouTube match for Spotify track")
                yt_id = results[0].get("video_id", "")
                if not yt_id:
                    raise HTTPException(status_code=404, detail="No YouTube match for Spotify track")
                mp3_path = await download_manager.download(yt_id)
                # Symlink or copy so sp_ ID maps to the file
                sp_path = settings.DOWNLOAD_DIR / f"{video_id}.mp3"
                if not sp_path.exists() and mp3_path.exists():
                    import shutil
                    shutil.copy2(mp3_path, sp_path)
                mp3_path = sp_path
            elif video_id.startswith("vk_"):
                # VK Music — need to re-fetch URL (temporary links)
                raise HTTPException(status_code=501, detail="VK streaming not supported in TMA yet")
            elif video_id.isdigit():
                # Pure digit ID — legacy Yandex Music track stored without ym_ prefix
                from bot.services.yandex_provider import download_yandex
                track_id = int(video_id)
                mp3_path = await download_yandex(track_id, mp3_path)
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
                        cache_tmp_path = settings.DOWNLOAD_DIR / f"{video_id}.part"
                        should_cache_stream = upstream.status == 200 and not range_header

                        async def _iter_upstream():
                            tmp_file = None
                            bytes_written = 0
                            expected_size = None
                            if should_cache_stream:
                                try:
                                    expected_size = int(upstream.headers.get("Content-Length", "0")) or None
                                except Exception:
                                    expected_size = None
                                try:
                                    tmp_file = open(cache_tmp_path, "wb")
                                except Exception as e:
                                    logger.warning("Cannot open temp cache file for %s: %s", video_id, e)
                                    tmp_file = None
                            try:
                                async for chunk in upstream.content.iter_chunked(64 * 1024):
                                    if tmp_file is not None:
                                        tmp_file.write(chunk)
                                        bytes_written += len(chunk)
                                    yield chunk
                                if tmp_file is not None:
                                    tmp_file.flush()
                                    tmp_file.close()
                                    tmp_file = None
                                    is_complete = expected_size is None or bytes_written >= expected_size
                                    if is_complete and not mp3_path.exists():
                                        cache_tmp_path.replace(mp3_path)
                                    else:
                                        cache_tmp_path.unlink(missing_ok=True)
                            except Exception:
                                if tmp_file is not None:
                                    try:
                                        tmp_file.close()
                                    except Exception:
                                        pass
                                cache_tmp_path.unlink(missing_ok=True)
                                raise
                            finally:
                                upstream.close()

                        response_headers = {
                            "Accept-Ranges": upstream.headers.get("Accept-Ranges", "bytes"),
                            "Cache-Control": "no-store",
                        }
                        content_length = upstream.headers.get("Content-Length")
                        content_range = upstream.headers.get("Content-Range")
                        if content_length:
                            response_headers["Content-Length"] = content_length
                        if content_range:
                            response_headers["Content-Range"] = content_range

                        return StreamingResponse(
                            _iter_upstream(),
                            status_code=upstream.status,
                            media_type=upstream.headers.get("Content-Type", "audio/mpeg"),
                            headers=response_headers,
                        )
                    upstream.close()

                # Fallback: coalesced download via download manager
                mp3_path = await download_manager.download(video_id)
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
            
            if start >= file_size:
                raise HTTPException(status_code=416, detail="Range not satisfiable")
            
            chunk_size = end - start + 1
            
            def iter_file():
                with open(mp3_path, "rb") as f:
                    f.seek(start)
                    remaining = chunk_size
                    while remaining > 0:
                        read_size = min(8192, remaining)
                        data = f.read(read_size)
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
    if video_id.startswith(("ym_", "sp_", "vk_", "sc_", "dz_")):
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


async def _load_state(user_id: int) -> PlayerState:
    r = await _get_redis()
    raw = await r.get(_state_key(user_id))
    if raw:
        state = PlayerState.model_validate_json(raw)
        return await _hydrate_state_covers(user_id, state)
    return PlayerState()


async def _save_state(user_id: int, state: PlayerState) -> None:
    r = await _get_redis()
    await r.setex(_state_key(user_id), 86400, state.model_dump_json())


async def _resolve_cover_url(source_id: str, source: str | None, current_cover: str | None = None) -> str | None:
    if current_cover:
        return current_cover

    normalized_source = (source or "youtube").lower()
    if normalized_source == "youtube" and source_id:
        return f"https://i.ytimg.com/vi/{source_id}/hqdefault.jpg"

    if normalized_source == "yandex" and source_id.startswith("ym_"):
        try:
            from bot.services.yandex_provider import fetch_yandex_track

            track_meta = await fetch_yandex_track(int(source_id[3:]))
            return track_meta.get("cover_url") if track_meta else None
        except Exception:
            return None

    return None


async def _refresh_missing_covers_in_state(user_id: int) -> None:
    """Best-effort refresh for older queue entries without cover URLs."""
    r = await _get_redis()
    raw = await r.get(_state_key(user_id))
    if not raw:
        return

    state = PlayerState.model_validate_json(raw)
    refreshed = await _hydrate_state_covers(user_id, state)
    await _save_state(user_id, refreshed)


async def _hydrate_track_cover(track: TrackSchema) -> tuple[TrackSchema, bool]:
    cover_url = await _resolve_cover_url(track.video_id, track.source, track.cover_url)
    if cover_url and cover_url != track.cover_url:
        track.cover_url = cover_url
        return track, True
    return track, False


async def _hydrate_state_covers(user_id: int, state: PlayerState) -> PlayerState:
    changed = False

    if state.queue:
        hydrated_queue = await asyncio.gather(*(_hydrate_track_cover(track) for track in state.queue))
        state.queue = [track for track, _ in hydrated_queue]
        changed = changed or any(updated for _, updated in hydrated_queue)

    if state.current_track:
        state.current_track, updated = await _hydrate_track_cover(state.current_track)
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
    await _refresh_missing_covers_in_state(user_id)
    return await _load_state(user_id)


@app.post("/api/player/action", response_model=PlayerState)
async def player_action(body: PlayerAction, user: dict = Depends(get_current_user)):
    user_id = user["id"]
    state = await _load_state(user_id)

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
        return await asyncio.gather(*(_db_track_to_schema(t) for t in tracks))


@app.get("/api/lyrics/{track_id}", response_model=LyricsResponse)
async def get_lyrics(track_id: str, user: dict = Depends(get_current_user)):
    # Try Redis cache first
    r = await _get_redis()
    cache_key = f"lyrics:{track_id}"
    cached = await r.get(cache_key)
    if cached:
        return LyricsResponse(track_id=track_id, lyrics=cached.decode() if isinstance(cached, bytes) else cached)

    # Fetch from Genius via search
    lyrics_text = await _fetch_lyrics(track_id)
    if lyrics_text:
        await r.setex(cache_key, 86400 * 7, lyrics_text)

    return LyricsResponse(track_id=track_id, lyrics=lyrics_text)


@app.get("/api/search", response_model=SearchResult)
async def search_tracks(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(default=10, ge=1, le=50),
    user: dict = Depends(get_current_user),
):
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
    from bot.db import upsert_track

    async with async_session() as session:
        pl = await session.get(Playlist, playlist_id)
        if not pl or pl.user_id != user["id"]:
            raise HTTPException(status_code=404, detail="Playlist not found")

        # Upsert track in DB
        track_data = {
            "source_id": body.video_id,
            "source": body.source,
            "title": body.title,
            "artist": body.artist,
            "duration": body.duration,
        }
        db_track = await upsert_track(track_data)

        # Check if already in playlist
        existing = (await session.execute(
            select(PlaylistTrack).where(
                PlaylistTrack.playlist_id == playlist_id,
                PlaylistTrack.track_id == db_track.id,
            )
        )).scalar_one_or_none()
        if existing:
            cnt = (await session.execute(
                select(func.count(PlaylistTrack.id)).where(PlaylistTrack.playlist_id == playlist_id)
            )).scalar() or 0
            return PlaylistSchema(id=pl.id, name=pl.name, track_count=cnt)

        # Get max position
        max_pos = (await session.execute(
            select(func.max(PlaylistTrack.position)).where(PlaylistTrack.playlist_id == playlist_id)
        )).scalar() or 0

        pt = PlaylistTrack(playlist_id=playlist_id, track_id=db_track.id, position=max_pos + 1)
        session.add(pt)
        await session.commit()

        cnt = (await session.execute(
            select(func.count(PlaylistTrack.id)).where(PlaylistTrack.playlist_id == playlist_id)
        )).scalar() or 0
        return PlaylistSchema(id=pl.id, name=pl.name, track_count=cnt)


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
    return {"ok": True}


# ── Helpers ──────────────────────────────────────────────────────────────

async def _get_track_by_source_id(source_id: str) -> TrackSchema | None:
    from sqlalchemy import select
    from bot.models.base import async_session
    from bot.models.track import Track
    from bot.utils import fmt_duration

    async with async_session() as session:
        t = (await session.execute(
            select(Track).where(Track.source_id == source_id)
        )).scalar_one_or_none()
        if t:
            return await _db_track_to_schema(t)
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


# ── Queue Reorder ────────────────────────────────────────────────────────

class ReorderRequest(BaseModel):
    from_index: int
    to_index: int


@app.post("/api/player/reorder", response_model=PlayerState)
async def reorder_queue(body: ReorderRequest, user: dict = Depends(get_current_user)):
    """Reorder a track in the queue."""
    user_id = user["id"]
    state = await _load_state(user_id)
    
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


# ── Frontend SPA serving ────────────────────────────────────────────────

_FRONTEND_DIST = Path(__file__).resolve().parent / "frontend" / "dist"

if _FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="static_assets")

    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        """Serve index.html for any non-API route (SPA fallback)."""
        file_path = _FRONTEND_DIST / full_path
        if full_path and file_path.is_file() and _FRONTEND_DIST in file_path.resolve().parents:
            return FileResponse(file_path)
        return FileResponse(_FRONTEND_DIST / "index.html")
