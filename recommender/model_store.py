"""ML Model Store - Thread-safe singleton for ML model lifecycle.

Handles loading, storing, and atomic swapping of trained models
(ALS and Word2Vec) without service downtime.

Models are stored on disk with versioning:
    data/models/
      als/
        model_v001.npz     # ALS model (numpy arrays)
        mappings_v001.json  # user_id -> idx, track_id -> idx
        latest.txt          # "001" -- pointer to current version
      w2v/
        model_v001.bin      # Word2Vec model (gensim format)
        latest.txt
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]

from bot.config import settings

logger = logging.getLogger(__name__)

# Backward-compatible module-level model directory (tests patch this symbol).
_MODEL_DIR = Path(settings.ML_MODEL_DIR)


class ModelStore:
    """Thread-safe singleton for managing ML model lifecycle.
    
    Usage:
        store = ModelStore.get()
        await store.load_latest()
        if store.is_ready:
            user_idx = store.get_user_idx(user_id)
            recs = store.recommend_for_user(user_idx, n=50)
    """
    
    _instance: "ModelStore | None" = None
    _lock: asyncio.Lock | None = None
    
    def __init__(self, base_dir: Path):
        self._base_dir = base_dir
        self._als_dir = base_dir / "als"
        self._w2v_dir = base_dir / "w2v"
        
        # ALS model components
        self._user_factors: np.ndarray | None = None
        self._item_factors: np.ndarray | None = None
        
        # Word2Vec model (gensim KeyedVectors)
        self._w2v_model: Any = None
        
        # Mappings
        self._user_map: dict[int, int] = {}     # user_id -> matrix idx
        self._track_map: dict[int, int] = {}    # track_id -> matrix idx
        self._track_reverse: dict[int, int] = {}  # matrix idx -> track_id
        self._source_map: dict[str, int] = {}   # source_id -> track_id (for w2v)
        
        self._version: int = 0
        
        # Ensure directories exist
        self._als_dir.mkdir(parents=True, exist_ok=True)
        self._w2v_dir.mkdir(parents=True, exist_ok=True)
    
    @classmethod
    def get(cls) -> "ModelStore":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls(Path(settings.ML_MODEL_DIR))
            cls._lock = asyncio.Lock()
        return cls._instance
    
    @property
    def is_ready(self) -> bool:
        """Check if models are loaded and ready for inference."""
        return self._user_factors is not None and self._item_factors is not None
    
    @property
    def w2v_ready(self) -> bool:
        """Check if Word2Vec model is loaded."""
        return self._w2v_model is not None
    
    @property
    def version(self) -> int:
        """Current model version."""
        return self._version
    
    @property
    def n_users(self) -> int:
        """Number of users in ALS model."""
        return len(self._user_map)
    
    @property
    def n_tracks(self) -> int:
        """Number of tracks in ALS model."""
        return len(self._track_map)
    
    async def load_latest(self) -> bool:
        """Load latest models from disk. Returns True if loaded."""
        try:
            als_loaded = await self._load_als()
            w2v_loaded = await self._load_w2v()
            
            if als_loaded:
                logger.info(
                    f"ModelStore: loaded ALS v{self._version} "
                    f"({self.n_users} users, {self.n_tracks} tracks)"
                )
            if w2v_loaded:
                logger.info(
                    f"ModelStore: loaded Word2Vec "
                    f"({len(self._w2v_model.key_to_index) if self._w2v_model else 0} tracks)"
                )
            
            return als_loaded
            
        except Exception as e:
            logger.error(f"ModelStore: failed to load models: {e}")
            return False
    
    async def _load_als(self) -> bool:
        """Load ALS model and mappings from disk."""
        latest_file = self._als_dir / "latest.txt"
        if not latest_file.exists():
            # Try legacy format
            return await self._load_als_legacy()
        
        version_str = latest_file.read_text().strip()
        version = int(version_str)
        
        model_file = self._als_dir / f"model_v{version_str}.npz"
        mappings_file = self._als_dir / f"mappings_v{version_str}.json"
        
        if not model_file.exists() or not mappings_file.exists():
            logger.warning(f"ModelStore: ALS v{version} files missing")
            return False
        
        def _load():
            data = np.load(model_file)
            with open(mappings_file, "r") as f:
                mappings = json.load(f)
            return data, mappings
        
        data, mappings = await asyncio.to_thread(_load)
        
        async with self._lock:
            self._user_factors = data["user_factors"]
            self._item_factors = data["item_factors"]
            self._user_map = {int(k): v for k, v in mappings["user_map"].items()}
            self._track_map = {int(k): v for k, v in mappings["track_map"].items()}
            self._track_reverse = {v: k for k, v in self._track_map.items()}
            self._source_map = mappings.get("source_map", {})
            self._version = version
        
        return True
    
    async def _load_als_legacy(self) -> bool:
        """Load legacy ALS format (als_*.npy files)."""
        d = self._base_dir
        paths = [
            d / "als_user_factors.npy",
            d / "als_item_factors.npy",
            d / "als_user_id_map.json",
            d / "als_track_id_map.json",
        ]
        if not all(p.exists() for p in paths):
            return False
        
        def _load():
            user_factors = np.load(paths[0])
            item_factors = np.load(paths[1])
            user_id_map = json.loads(paths[2].read_text(encoding="utf-8"))
            track_id_map = json.loads(paths[3].read_text(encoding="utf-8"))
            return user_factors, item_factors, user_id_map, track_id_map
        
        user_factors, item_factors, user_id_map, track_id_map = await asyncio.to_thread(_load)
        
        async with self._lock:
            self._user_factors = user_factors
            self._item_factors = item_factors
            self._user_map = {int(k): v for k, v in user_id_map.items()}
            self._track_map = {int(k): v for k, v in track_id_map.items()}
            self._track_reverse = {v: k for k, v in self._track_map.items()}
            self._version = 0
        
        logger.info("ModelStore: loaded legacy ALS format")
        return True
    
    async def _load_w2v(self) -> bool:
        """Load Word2Vec model from disk."""
        latest_file = self._w2v_dir / "latest.txt"
        if not latest_file.exists():
            # Try legacy format
            return await self._load_w2v_legacy()
        
        version_str = latest_file.read_text().strip()
        model_file = self._w2v_dir / f"model_v{version_str}.bin"
        
        if not model_file.exists():
            return False
        
        def _load():
            from gensim.models import KeyedVectors
            return KeyedVectors.load(str(model_file))
        
        try:
            model = await asyncio.to_thread(_load)
            async with self._lock:
                self._w2v_model = model
            return True
        except Exception as e:
            logger.error(f"ModelStore: failed to load Word2Vec: {e}")
            return False
    
    async def _load_w2v_legacy(self) -> bool:
        """Load legacy embeddings format."""
        emb_path = self._base_dir / "track_embeddings.npy"
        ids_path = self._base_dir / "embedding_track_ids.json"
        if not emb_path.exists() or not ids_path.exists():
            return False
        
        # Legacy format doesn't support W2V features, skip
        return False
    
    async def swap(
        self,
        user_factors: np.ndarray,
        item_factors: np.ndarray,
        user_map: dict[int, int],
        track_map: dict[int, int],
        source_map: dict[str, int],
        version: int,
        w2v_model: Any = None,
    ) -> None:
        """Atomically swap current models with new ones."""
        async with self._lock:
            self._user_factors = user_factors
            self._item_factors = item_factors
            self._user_map = user_map
            self._track_map = track_map
            self._track_reverse = {v: k for k, v in track_map.items()}
            self._source_map = source_map
            self._version = version
            
            if w2v_model is not None:
                self._w2v_model = w2v_model
        
        logger.info(f"ModelStore: swapped to v{version}")
    
    # ─── ALS Methods ─────────────────────────────────────────────────────
    
    def get_user_idx(self, user_id: int) -> int | None:
        """Get matrix index for user_id."""
        return self._user_map.get(user_id)
    
    def get_track_idx(self, track_id: int) -> int | None:
        """Get matrix index for track_id."""
        return self._track_map.get(track_id)
    
    def get_track_id(self, idx: int) -> int | None:
        """Get track_id from matrix index."""
        return self._track_reverse.get(idx)
    
    def get_user_factors(self) -> np.ndarray | None:
        return self._user_factors
    
    def get_item_factors(self) -> np.ndarray | None:
        return self._item_factors
    
    def recommend_for_user(
        self, user_idx: int, n: int = 50
    ) -> list[tuple[int, float]]:
        """Get top-N recommendations for user.
        
        Returns list of (track_idx, score) sorted by score descending.
        """
        if not self.is_ready or user_idx >= len(self._user_factors):
            return []
        
        user_vec = self._user_factors[user_idx]
        scores = np.dot(self._item_factors, user_vec)
        top_indices = np.argsort(scores)[::-1][:n * 2]
        
        result = []
        for idx in top_indices:
            track_id = self.get_track_id(int(idx))
            if track_id is not None:
                result.append((int(idx), float(scores[idx])))
            if len(result) >= n:
                break
        
        return result
    
    # ─── Word2Vec Methods ────────────────────────────────────────────────
    
    def get_w2v_model(self) -> Any:
        return self._w2v_model
    
    def get_similar_tracks(
        self, source_id: str, topn: int = 20
    ) -> list[tuple[str, float]]:
        """Get similar tracks by source_id using Word2Vec."""
        if not self.w2v_ready:
            return []
        if source_id not in self._w2v_model.key_to_index:
            return []
        try:
            return self._w2v_model.most_similar(source_id, topn=topn)
        except KeyError:
            return []
    
    def get_track_vector(self, source_id: str) -> np.ndarray | None:
        """Get embedding vector for track."""
        if not self.w2v_ready:
            return None
        if source_id not in self._w2v_model.key_to_index:
            return None
        return self._w2v_model[source_id]
    
    def get_session_vector(self, source_ids: list[str]) -> np.ndarray | None:
        """Get average embedding of multiple tracks."""
        if not self.w2v_ready:
            return None
        vectors = [v for sid in source_ids if (v := self.get_track_vector(sid)) is not None]
        if not vectors:
            return None
        return np.mean(vectors, axis=0)
    
    # ─── Save Methods ────────────────────────────────────────────────────
    
    async def save_als(
        self,
        user_factors: np.ndarray,
        item_factors: np.ndarray,
        user_map: dict[int, int],
        track_map: dict[int, int],
        source_map: dict[str, int],
        version: int,
    ) -> Path:
        """Save ALS model to disk."""
        version_str = f"{version:03d}"
        model_file = self._als_dir / f"model_v{version_str}.npz"
        mappings_file = self._als_dir / f"mappings_v{version_str}.json"
        latest_file = self._als_dir / "latest.txt"
        
        def _save():
            np.savez_compressed(
                model_file,
                user_factors=user_factors,
                item_factors=item_factors,
            )
            with open(mappings_file, "w") as f:
                json.dump({
                    "user_map": {str(k): v for k, v in user_map.items()},
                    "track_map": {str(k): v for k, v in track_map.items()},
                    "source_map": source_map,
                }, f)
            latest_file.write_text(version_str)
        
        await asyncio.to_thread(_save)
        return model_file
    
    async def save_w2v(self, model: Any, version: int) -> Path:
        """Save Word2Vec model to disk."""
        version_str = f"{version:03d}"
        model_file = self._w2v_dir / f"model_v{version_str}.bin"
        latest_file = self._w2v_dir / "latest.txt"
        
        def _save():
            model.save(str(model_file))
            latest_file.write_text(version_str)
        
        await asyncio.to_thread(_save)
        return model_file
    
    def get_latest_version(self) -> int:
        """Get the latest model version from disk."""
        latest_file = self._als_dir / "latest.txt"
        if latest_file.exists():
            return int(latest_file.read_text().strip())
        return 0


# ─── Legacy Functions (for backward compatibility) ───────────────────────

def ensure_model_dir() -> Path:
    d = _MODEL_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def model_exists() -> bool:
    """Check if a trained model exists."""
    store = ModelStore.get()
    return store.is_ready or (ensure_model_dir() / "als_item_factors.npy").exists()


def load_als() -> tuple[np.ndarray, np.ndarray, dict, dict] | None:
    """Load ALS factors and mappings (legacy sync interface)."""
    d = ensure_model_dir()
    paths = [
        d / "als_user_factors.npy",
        d / "als_item_factors.npy",
        d / "als_user_id_map.json",
        d / "als_track_id_map.json",
    ]
    if not all(p.exists() for p in paths):
        return None
    user_factors = np.load(paths[0])
    item_factors = np.load(paths[1])
    user_id_map = json.loads(paths[2].read_text(encoding="utf-8"))
    track_id_map = json.loads(paths[3].read_text(encoding="utf-8"))
    return user_factors, item_factors, user_id_map, track_id_map


def save_als(user_factors: np.ndarray, item_factors: np.ndarray,
             user_id_map: dict, track_id_map: dict) -> None:
    """Save ALS model (legacy sync interface)."""
    d = ensure_model_dir()
    np.save(d / "als_user_factors.npy", user_factors)
    np.save(d / "als_item_factors.npy", item_factors)
    (d / "als_user_id_map.json").write_text(json.dumps(user_id_map), encoding="utf-8")
    (d / "als_track_id_map.json").write_text(json.dumps(track_id_map), encoding="utf-8")


def load_embeddings() -> tuple[np.ndarray, list[int]] | None:
    """Load track embeddings and track IDs (legacy sync interface)."""
    d = ensure_model_dir()
    emb_path = d / "track_embeddings.npy"
    ids_path = d / "embedding_track_ids.json"
    if not emb_path.exists() or not ids_path.exists():
        return None
    embeddings = np.load(emb_path)
    track_ids = json.loads(ids_path.read_text(encoding="utf-8"))
    return embeddings, [int(tid) for tid in track_ids]


def save_embeddings(embeddings: np.ndarray, track_ids: list[int]) -> None:
    """Save track embeddings and track IDs (legacy sync interface)."""
    d = ensure_model_dir()
    np.save(d / "track_embeddings.npy", embeddings)
    (d / "embedding_track_ids.json").write_text(
        json.dumps([int(tid) for tid in track_ids]), encoding="utf-8"
    )


def load_popularity() -> dict[int, float] | None:
    d = ensure_model_dir()
    p = d / "popularity_scores.json"
    if not p.exists():
        return None
    raw = json.loads(p.read_text(encoding="utf-8"))
    return {int(k): v for k, v in raw.items()}


def save_popularity(scores: dict[int, float]) -> None:
    d = ensure_model_dir()
    (d / "popularity_scores.json").write_text(
        json.dumps({str(k): v for k, v in scores.items()}), encoding="utf-8"
    )


# ─── Module-level singleton ──────────────────────────────────────────────

# Convenience instance for direct import:
#   from recommender.model_store import model_store
#   if model_store.is_ready:
#       ...
model_store = ModelStore.get()
