"""Data Extractor - Extract training data from database.

Extracts user-item interactions from ListeningHistory and builds:
1. Sparse interaction matrix for ALS training
2. Sessions for Word2Vec training

Supports weighted implicit feedback:
- play: 1.0
- like: 2.0
- dislike: -1.0
- skip: 0.3
- Full listen (>80%): 1.5x multiplier
- Partial (<30%): 0.5x multiplier
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    import numpy as np
    import scipy.sparse as sp
except ImportError:
    np = None  # type: ignore[assignment]
    sp = None  # type: ignore[assignment]

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import async_session
from bot.models.track import ListeningHistory, Track
from recommender.config import (
    ACTION_WEIGHTS,
    FULL_LISTEN_MULTIPLIER,
    PARTIAL_LISTEN_MULTIPLIER,
    MLConfig,
)

logger = logging.getLogger(__name__)


async def extract_interactions() -> tuple[
    sp.csr_matrix,
    dict[int, int],  # user_id -> idx
    dict[int, int],  # track_id -> idx
    dict[str, int],  # source_id -> track_id
]:
    """Extract user-item interaction matrix from database.
    
    Returns:
    - CSR sparse matrix of shape (n_users, n_tracks)
    - user_id -> matrix index mapping
    - track_id -> matrix index mapping
    - source_id -> track_id mapping (for W2V)
    """
    async with async_session() as session:
        # Get all interactions with valid tracks
        result = await session.execute(
            select(
                ListeningHistory.user_id,
                ListeningHistory.track_id,
                ListeningHistory.action,
                ListeningHistory.listen_duration,
                Track.duration,
                Track.source_id,
                Track.file_id,
            )
            .join(Track, Track.id == ListeningHistory.track_id)
            .where(
                ListeningHistory.track_id.isnot(None),
                Track.file_id.isnot(None),  # Only tracks we can play
            )
        )
        
        interactions = list(result)
    
    if not interactions:
        logger.warning("No interactions found for training")
        return sp.csr_matrix((0, 0)), {}, {}, {}
    
    # Build ID mappings
    user_ids = sorted(set(row[0] for row in interactions))
    track_ids = sorted(set(row[1] for row in interactions))
    
    user_map = {uid: idx for idx, uid in enumerate(user_ids)}
    track_map = {tid: idx for idx, tid in enumerate(track_ids)}
    
    # Build source_id -> track_id mapping
    source_map = {}
    for row in interactions:
        track_id, source_id = row[1], row[5]
        if source_id and track_id:
            source_map[source_id] = track_id
    
    # Build weighted interaction matrix
    weights = defaultdict(float)
    
    for user_id, track_id, action, listen_dur, track_dur, _, _ in interactions:
        user_idx = user_map[user_id]
        track_idx = track_map[track_id]
        
        # Base weight from action
        weight = ACTION_WEIGHTS.get(action, 0.5)
        
        # Apply listen ratio multiplier
        if listen_dur and track_dur and track_dur > 0:
            ratio = listen_dur / track_dur
            if ratio > 0.8:
                weight *= FULL_LISTEN_MULTIPLIER
            elif ratio < 0.3:
                weight *= PARTIAL_LISTEN_MULTIPLIER
        
        # Accumulate weights (same user-track pair can have multiple interactions)
        weights[(user_idx, track_idx)] += weight
    
    # Convert to COO format
    rows = []
    cols = []
    data = []
    
    for (user_idx, track_idx), weight in weights.items():
        rows.append(user_idx)
        cols.append(track_idx)
        data.append(weight)
    
    # Create CSR matrix
    matrix = sp.csr_matrix(
        (data, (rows, cols)),
        shape=(len(user_ids), len(track_ids)),
        dtype=np.float32,
    )
    
    logger.info(
        f"Extracted interactions: {len(user_ids)} users, "
        f"{len(track_ids)} tracks, {len(data)} interactions"
    )
    
    return matrix, user_map, track_map, source_map


async def extract_sessions(
    min_session_len: int = 2,
    session_gap_minutes: int | None = None,
) -> list[list[str]]:
    """Extract listening sessions for Word2Vec training.
    
    A session is a sequence of play events by one user where
    consecutive events are within session_gap_minutes of each other.
    
    Returns list of sessions, each session is a list of source_ids.
    """
    cfg = MLConfig.get()
    gap_minutes = session_gap_minutes or cfg.session_gap_minutes
    
    async with async_session() as session:
        # Get all play events with tracks
        result = await session.execute(
            select(
                ListeningHistory.user_id,
                Track.source_id,
                ListeningHistory.created_at,
            )
            .join(Track, Track.id == ListeningHistory.track_id)
            .where(
                ListeningHistory.action == "play",
                ListeningHistory.track_id.isnot(None),
                Track.file_id.isnot(None),
            )
            .order_by(
                ListeningHistory.user_id,
                ListeningHistory.created_at,
            )
        )
        
        events = list(result)
    
    if not events:
        return []
    
    # Group by user and split into sessions
    sessions = []
    current_session: list[str] = []
    current_user = None
    last_time = None
    gap_delta = timedelta(minutes=gap_minutes)
    
    for user_id, source_id, created_at in events:
        # New user = new session
        if user_id != current_user:
            if len(current_session) >= min_session_len:
                sessions.append(current_session)
            current_session = [source_id]
            current_user = user_id
            last_time = created_at
            continue
        
        # Check time gap
        if last_time and (created_at - last_time) > gap_delta:
            # Gap too large = new session
            if len(current_session) >= min_session_len:
                sessions.append(current_session)
            current_session = [source_id]
        else:
            current_session.append(source_id)
        
        last_time = created_at
    
    # Don't forget last session
    if len(current_session) >= min_session_len:
        sessions.append(current_session)
    
    logger.info(f"Extracted {len(sessions)} sessions for W2V training")
    return sessions


async def get_training_stats() -> dict[str, Any]:
    """Get statistics about available training data."""
    async with async_session() as session:
        # Count interactions
        from sqlalchemy.sql import func
        
        interactions_result = await session.execute(
            select(func.count())
            .select_from(ListeningHistory)
            .where(ListeningHistory.track_id.isnot(None))
        )
        n_interactions = interactions_result.scalar() or 0
        
        # Count unique users
        users_result = await session.execute(
            select(func.count(func.distinct(ListeningHistory.user_id)))
            .select_from(ListeningHistory)
            .where(ListeningHistory.track_id.isnot(None))
        )
        n_users = users_result.scalar() or 0
        
        # Count unique tracks with file_id
        tracks_result = await session.execute(
            select(func.count())
            .select_from(Track)
            .where(Track.file_id.isnot(None))
        )
        n_tracks = tracks_result.scalar() or 0
        
        # Count play actions
        plays_result = await session.execute(
            select(func.count())
            .select_from(ListeningHistory)
            .where(
                ListeningHistory.track_id.isnot(None),
                ListeningHistory.action == "play",
            )
        )
        n_plays = plays_result.scalar() or 0
    
    return {
        "n_interactions": n_interactions,
        "n_users": n_users,
        "n_tracks": n_tracks,
        "n_plays": n_plays,
    }


async def split_train_test(
    matrix: sp.csr_matrix,
    test_ratio: float = 0.2,
) -> tuple[sp.csr_matrix, sp.csr_matrix]:
    """Split interaction matrix into train/test by time.
    
    For each user, last X% of interactions go to test.
    """
    # This is tricky with CSR format - simplified approach:
    # randomly mask some entries for test
    
    from scipy.sparse import lil_matrix
    
    train = lil_matrix(matrix.shape, dtype=np.float32)
    test = lil_matrix(matrix.shape, dtype=np.float32)
    
    cx = matrix.tocoo()
    
    # Group by user
    user_interactions: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for i, j, v in zip(cx.row, cx.col, cx.data):
        user_interactions[i].append((j, v))
    
    for user_idx, items in user_interactions.items():
        n_items = len(items)
        n_test = max(1, int(n_items * test_ratio))
        
        # Last n_test items go to test
        train_items = items[:-n_test]
        test_items = items[-n_test:]
        
        for col, val in train_items:
            train[user_idx, col] = val
        for col, val in test_items:
            test[user_idx, col] = val
    
    return train.tocsr(), test.tocsr()
