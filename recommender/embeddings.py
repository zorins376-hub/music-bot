"""
embeddings.py — Word2Vec track embeddings from listening sessions.

Listening sessions are split by 30-min gaps. Each session is a "sentence"
of track IDs. We train a Word2Vec model to get track embedding vectors.
"""
import logging
from collections import defaultdict
from datetime import timedelta

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]

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


class TrackEmbeddings:
    """Wrapper around ModelStore for track similarity using Word2Vec embeddings.
    
    Usage:
        from recommender.model_store import ModelStore
        from recommender.embeddings import TrackEmbeddings
        
        store = ModelStore.get()
        emb = TrackEmbeddings(store)
        
        similar = emb.get_similar_tracks("dQw4w9WgXcQ", topn=20)
        # Returns: [("abc123", 0.95), ("xyz789", 0.87), ...]
    """
    
    def __init__(self, model_store: "ModelStore | None" = None):
        if model_store is None:
            from recommender.model_store import ModelStore
            model_store = ModelStore.get()
        self._store = model_store
    
    def get_similar_tracks(
        self, source_id: str, topn: int = 20
    ) -> list[tuple[str, float]]:
        """Get similar tracks by source_id using Word2Vec cosine similarity.
        
        Returns list of (source_id, similarity_score) pairs.
        Returns empty list if track not in vocabulary or model not loaded.
        """
        return self._store.get_similar_tracks(source_id, topn)
    
    def get_track_vector(self, source_id: str) -> np.ndarray | None:
        """Get embedding vector for a single track.
        
        Returns None if track not in vocabulary or model not loaded.
        """
        return self._store.get_track_vector(source_id)
    
    def get_session_vector(self, source_ids: list[str]) -> np.ndarray | None:
        """Get average embedding of multiple tracks.
        
        Useful for computing "user taste vector" from recent listens.
        Returns None if no tracks found or model not loaded.
        """
        return self._store.get_session_vector(source_ids)
    
    def cosine_similarity(
        self, source_id_a: str, source_id_b: str
    ) -> float | None:
        """Compute cosine similarity between two tracks.
        
        Returns None if either track not in vocabulary.
        """
        vec_a = self.get_track_vector(source_id_a)
        vec_b = self.get_track_vector(source_id_b)
        
        if vec_a is None or vec_b is None:
            return None
        
        # Cosine similarity
        dot = np.dot(vec_a, vec_b)
        norm_a = np.linalg.norm(vec_a)
        norm_b = np.linalg.norm(vec_b)
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return float(dot / (norm_a * norm_b))
    
    @staticmethod
    def cosine_similarity_vectors(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
        """Compute cosine similarity between two pre-fetched vectors.
        
        Args:
            vec_a: First embedding vector (numpy array)
            vec_b: Second embedding vector (numpy array)
            
        Returns:
            Cosine similarity score (-1 to 1)
        """
        dot = np.dot(vec_a, vec_b)
        norm_a = np.linalg.norm(vec_a)
        norm_b = np.linalg.norm(vec_b)
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return float(dot / (norm_a * norm_b))
    
    def get_user_taste_similarity(
        self, recent_track_ids: list[str], candidate_id: str
    ) -> float | None:
        """Compute similarity between user's recent tracks and a candidate track.
        
        Uses average embedding of recent tracks as "taste vector".
        """
        taste_vec = self.get_session_vector(recent_track_ids)
        candidate_vec = self.get_track_vector(candidate_id)
        
        if taste_vec is None or candidate_vec is None:
            return None
        
        dot = np.dot(taste_vec, candidate_vec)
        norm_a = np.linalg.norm(taste_vec)
        norm_b = np.linalg.norm(candidate_vec)
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return float(dot / (norm_a * norm_b))
    
    @property
    def is_ready(self) -> bool:
        """Check if Word2Vec model is loaded and ready."""
        return self._store.w2v_ready
