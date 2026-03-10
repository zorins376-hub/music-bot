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
import json
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from bot.config import settings
from bot.models.base import init_db
from webapp.auth import verify_init_data
from webapp.schemas import (
    LyricsResponse,
    PlayerAction,
    PlayerState,
    PlaylistSchema,
    SearchResult,
    TrackSchema,
)

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
    yield


# ── App ──────────────────────────────────────────────────────────────────

app = FastAPI(title="TMA Player", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Helper: Redis player state ──────────────────────────────────────────

async def _get_redis():
    from bot.services.cache import cache
    return cache.redis


def _state_key(user_id: int) -> str:
    return f"tma:player:{user_id}"


async def _load_state(user_id: int) -> PlayerState:
    r = await _get_redis()
    raw = await r.get(_state_key(user_id))
    if raw:
        return PlayerState.model_validate_json(raw)
    return PlayerState()


async def _save_state(user_id: int, state: PlayerState) -> None:
    r = await _get_redis()
    await r.setex(_state_key(user_id), 86400, state.model_dump_json())


# ── Endpoints ────────────────────────────────────────────────────────────

@app.get("/api/player/state/{user_id}", response_model=PlayerState)
async def get_player_state(user_id: int, user: dict = Depends(get_current_user)):
    if user.get("id") != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
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
                # Load track info from DB
                track = await _get_track_by_source_id(body.track_id)
                if track:
                    state.queue.append(track)
                    state.position = len(state.queue) - 1
        state.is_playing = True

    elif body.action == "pause":
        state.is_playing = False

    elif body.action == "next":
        if state.queue:
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
        return [_db_track_to_schema(t) for t in tracks]


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
        )
        for r in results
    ]
    return SearchResult(tracks=tracks, total=len(tracks))


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
            return _db_track_to_schema(t)
    return None


def _db_track_to_schema(t) -> TrackSchema:
    from bot.utils import fmt_duration
    return TrackSchema(
        video_id=t.source_id,
        title=t.title or "Unknown",
        artist=t.artist or "Unknown",
        duration=t.duration or 0,
        duration_fmt=fmt_duration(t.duration),
        source=t.source or "youtube",
        file_id=t.file_id,
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
