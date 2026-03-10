"""
embeddings.py — Word2Vec track embeddings from listening sessions.

Listening sessions are split by 30-min gaps. Each session is a "sentence"
of track IDs. We train a Word2Vec model to get track embedding vectors.
"""
import logging
from collections import defaultdict
from datetime import timedelta

import numpy as np

logger = logging.getLogger(__name__)

# Session gap threshold: 30 minutes between plays = new session
_SESSION_GAP = timedelta(minutes=30)
_EMBEDDING_DIM = 64
_MIN_SESSIONS = 10


def build_sessions(plays: list[tuple[int, int, object]]) -> list[list[str]]:
    """
    Build listening sessions from play history.

    Args:
        plays: list of (user_id, track_id, created_at) tuples, ordered by user_id, created_at

    Returns:
        list of sessions, each session is a list of track_id strings
    """
    sessions: list[list[str]] = []
    current_user = None
    current_session: list[str] = []
    last_time = None

    for user_id, track_id, created_at in plays:
        if user_id != current_user:
            if len(current_session) >= 2:
                sessions.append(current_session)
            current_session = [str(track_id)]
            current_user = user_id
            last_time = created_at
            continue

        if last_time and (created_at - last_time) > _SESSION_GAP:
            if len(current_session) >= 2:
                sessions.append(current_session)
            current_session = []

        current_session.append(str(track_id))
        last_time = created_at

    if len(current_session) >= 2:
        sessions.append(current_session)

    return sessions


def train_embeddings(sessions: list[list[str]]) -> tuple[np.ndarray, list[int]] | None:
    """
    Train Word2Vec on listening sessions.

    Returns (embeddings_matrix, track_ids) or None if insufficient data.
    """
    if len(sessions) < _MIN_SESSIONS:
        logger.info("Not enough sessions for embeddings: %d < %d", len(sessions), _MIN_SESSIONS)
        return None

    try:
        from gensim.models import Word2Vec
    except ImportError:
        logger.warning("gensim not installed, skipping embeddings")
        return None

    model = Word2Vec(
        sentences=sessions,
        vector_size=_EMBEDDING_DIM,
        window=5,
        min_count=2,
        workers=2,
        epochs=10,
        sg=1,  # skip-gram
    )

    track_ids = [int(w) for w in model.wv.index_to_key]
    embeddings = np.array([model.wv[str(tid)] for tid in track_ids], dtype=np.float32)

    # L2 normalize for cosine similarity
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1
    embeddings = embeddings / norms

    logger.info("Trained embeddings: %d tracks, dim=%d", len(track_ids), _EMBEDDING_DIM)
    return embeddings, track_ids
