"""Profile Auto-Updater - Automatic user profile recalculation.

Computes user preferences from listening history:
- fav_genres: top 5 genres (weighted by recency)
- fav_artists: top 5 artists (weighted by recency)
- avg_bpm: average BPM of last 100 tracks
- preferred_hours: top 4 listening hours (UTC)
- fav_vibe: inferred from BPM/genre clusters

Triggered after every 10 play events via bot/db.py
"""

import asyncio
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from math import log2

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import async_session
from bot.models.track import ListeningHistory, Track
from bot.models.user import User

logger = logging.getLogger(__name__)


async def update_user_profile_full(user_id: int) -> None:
    """Full profile recalculation based on listening history.
    
    Updates:
    - fav_genres (top 5)
    - fav_artists (top 5)
    - avg_bpm (last 100 tracks)
    - preferred_hours (top 4 UTC hours)
    - fav_vibe (inferred)
    """
    try:
        async with async_session() as session:
            # Check if user exists and is onboarded
            user = await session.get(User, user_id)
            if not user:
                return
            
            # Get listening history data
            top_genres = await _get_top_genres(session, user_id)
            top_artists = await _get_top_artists(session, user_id)
            avg_bpm = await _get_avg_bpm(session, user_id)
            preferred_hours = await _get_preferred_hours(session, user_id)
            fav_vibe = _infer_vibe(avg_bpm, top_genres)
            
            # Build update dict, only update if we have data
            update_values = {}
            
            if top_genres:
                update_values["fav_genres"] = top_genres[:5]
            if top_artists:
                update_values["fav_artists"] = top_artists[:5]
            if avg_bpm:
                update_values["avg_bpm"] = avg_bpm
            if preferred_hours:
                update_values["preferred_hours"] = preferred_hours[:4]
            if fav_vibe:
                update_values["fav_vibe"] = fav_vibe
            
            if update_values:
                await session.execute(
                    update(User).where(User.id == user_id).values(**update_values)
                )
                await session.commit()
                logger.debug(f"Profile updated for user {user_id}: {list(update_values.keys())}")
                
    except Exception as e:
        logger.error(f"Profile update failed for user {user_id}: {e}")


async def _get_top_genres(session: AsyncSession, user_id: int, limit: int = 10) -> list[str]:
    """Get top genres weighted by recency.
    
    More recent listens have higher weight (exponential decay).
    """
    # Get plays from last 90 days with genres
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    
    result = await session.execute(
        select(Track.genre, ListeningHistory.created_at)
        .join(Track, Track.id == ListeningHistory.track_id)
        .where(
            ListeningHistory.user_id == user_id,
            ListeningHistory.action == "play",
            ListeningHistory.track_id.isnot(None),
            Track.genre.isnot(None),
            ListeningHistory.created_at >= cutoff,
        )
        .order_by(ListeningHistory.created_at.desc())
    )
    
    # Apply recency weighting
    genre_weights: Counter[str] = Counter()
    now = datetime.now(timezone.utc)
    
    for genre, created_at in result:
        if not genre:
            continue
        # Exponential decay: recent = 1.0, 30 days ago = 0.5, 60 days = 0.25
        days_ago = (now - created_at).days
        weight = 2 ** (-days_ago / 30)
        genre_weights[genre] += weight
    
    # Return sorted by weight
    return [g for g, _ in genre_weights.most_common(limit)]


async def _get_top_artists(session: AsyncSession, user_id: int, limit: int = 10) -> list[str]:
    """Get top artists weighted by recency."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    
    result = await session.execute(
        select(Track.artist, ListeningHistory.created_at)
        .join(Track, Track.id == ListeningHistory.track_id)
        .where(
            ListeningHistory.user_id == user_id,
            ListeningHistory.action == "play",
            ListeningHistory.track_id.isnot(None),
            Track.artist.isnot(None),
            ListeningHistory.created_at >= cutoff,
        )
        .order_by(ListeningHistory.created_at.desc())
    )
    
    artist_weights: Counter[str] = Counter()
    now = datetime.now(timezone.utc)
    
    for artist, created_at in result:
        if not artist:
            continue
        days_ago = (now - created_at).days
        weight = 2 ** (-days_ago / 30)
        artist_weights[artist] += weight
    
    return [a for a, _ in artist_weights.most_common(limit)]


async def _get_avg_bpm(session: AsyncSession, user_id: int) -> int | None:
    """Get average BPM from last 100 tracks with BPM data."""
    result = await session.execute(
        select(Track.bpm)
        .join(ListeningHistory, Track.id == ListeningHistory.track_id)
        .where(
            ListeningHistory.user_id == user_id,
            ListeningHistory.action == "play",
            Track.bpm.isnot(None),
            Track.bpm > 0,
        )
        .order_by(ListeningHistory.created_at.desc())
        .limit(100)
    )
    
    bpms = [row[0] for row in result if row[0]]
    if not bpms:
        return None
    
    return int(sum(bpms) / len(bpms))


async def _get_preferred_hours(session: AsyncSession, user_id: int) -> list[int]:
    """Get preferred listening hours (UTC).
    
    Returns top 4 hours by play count.
    """
    # Check if we're using PostgreSQL or SQLite
    dialect = session.get_bind().dialect.name
    
    if dialect == "postgresql":
        # PostgreSQL: use EXTRACT
        hour_expr = func.extract("hour", ListeningHistory.created_at)
    else:
        # SQLite: use strftime
        hour_expr = func.cast(
            func.strftime("%H", ListeningHistory.created_at),
            type_=func.integer()
        )
    
    result = await session.execute(
        select(hour_expr.label("hour"), func.count().label("cnt"))
        .where(
            ListeningHistory.user_id == user_id,
            ListeningHistory.action == "play",
        )
        .group_by("hour")
        .order_by(func.count().desc())
        .limit(4)
    )
    
    return [int(row[0]) for row in result if row[0] is not None]


def _infer_vibe(avg_bpm: int | None, genres: list[str]) -> str | None:
    """Infer preferred vibe from BPM and genres.
    
    Vibes:
    - "chill": low BPM or ambient/lofi genres
    - "energetic": high BPM or electronic/dance genres
    - "deep": medium BPM with techno/house
    - "intense": very high BPM or metal/hardcore
    - "mellow": medium-low BPM, indie/acoustic
    """
    if not avg_bpm and not genres:
        return None
    
    # Genre-based inference
    genre_set = set(g.lower() for g in (genres or []))
    
    chill_genres = {"ambient", "lofi", "chillout", "downtempo", "lo-fi", "jazz", "classical"}
    energy_genres = {"edm", "electronic", "dance", "trance", "dnb", "drum and bass"}
    deep_genres = {"techno", "house", "deep house", "tech house", "minimal"}
    intense_genres = {"metal", "hardcore", "hardstyle", "gabber", "industrial"}
    
    if genre_set & chill_genres:
        return "chill"
    if genre_set & intense_genres:
        return "intense"
    if genre_set & deep_genres:
        return "deep"
    if genre_set & energy_genres:
        return "energetic"
    
    # BPM-based fallback
    if avg_bpm:
        if avg_bpm < 90:
            return "chill"
        elif avg_bpm < 110:
            return "mellow"
        elif avg_bpm < 130:
            return "deep"
        elif avg_bpm < 150:
            return "energetic"
        else:
            return "intense"
    
    return None


def calculate_genre_diversity(genre_counts: dict[str, int]) -> float:
    """Calculate Shannon entropy normalized to [0, 1].
    
    Used to measure how diverse a user's taste is.
    0.0 = listens to only 1 genre
    1.0 = equal distribution across all genres
    """
    total = sum(genre_counts.values())
    if total == 0 or len(genre_counts) <= 1:
        return 0.0
    
    entropy = -sum(
        (c / total) * log2(c / total)
        for c in genre_counts.values()
        if c > 0
    )
    max_entropy = log2(len(genre_counts))
    
    return round(entropy / max_entropy, 3) if max_entropy > 0 else 0.0


async def trigger_profile_update(user_id: int) -> None:
    """Fire-and-forget profile update.
    
    Called from bot/db.py after play events.
    """
    asyncio.create_task(update_user_profile_full(user_id))
