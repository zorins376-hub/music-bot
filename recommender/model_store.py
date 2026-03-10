"""
model_store.py — Save / load ML model artifacts.

Models are stored in data/models/ as numpy/pickle files:
  - als_user_factors.npy, als_item_factors.npy
  - track_embeddings.npy, track_id_map.json
  - popularity_scores.json
"""
import json
import logging
from pathlib import Path

import numpy as np

from bot.config import settings

logger = logging.getLogger(__name__)

_MODEL_DIR = Path(settings.ML_MODEL_PATH)


def ensure_model_dir() -> Path:
    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    return _MODEL_DIR


def save_als(user_factors: np.ndarray, item_factors: np.ndarray,
             user_id_map: dict, track_id_map: dict) -> None:
    """Save ALS model factors and ID mappings."""
    d = ensure_model_dir()
    np.save(d / "als_user_factors.npy", user_factors)
    np.save(d / "als_item_factors.npy", item_factors)
    (d / "als_user_id_map.json").write_text(json.dumps(user_id_map), encoding="utf-8")
    (d / "als_track_id_map.json").write_text(json.dumps(track_id_map), encoding="utf-8")
    logger.info("ALS model saved: users=%d, items=%d", len(user_id_map), len(track_id_map))


def load_als() -> tuple[np.ndarray, np.ndarray, dict, dict] | None:
    """Load ALS factors and mappings. Returns None if not found."""
    d = _MODEL_DIR
    paths = [d / "als_user_factors.npy", d / "als_item_factors.npy",
             d / "als_user_id_map.json", d / "als_track_id_map.json"]
    if not all(p.exists() for p in paths):
        return None
    user_factors = np.load(paths[0])
    item_factors = np.load(paths[1])
    user_id_map = json.loads(paths[2].read_text(encoding="utf-8"))
    track_id_map = json.loads(paths[3].read_text(encoding="utf-8"))
    return user_factors, item_factors, user_id_map, track_id_map


def save_embeddings(embeddings: np.ndarray, track_ids: list[int]) -> None:
    """Save Word2Vec track embeddings."""
    d = ensure_model_dir()
    np.save(d / "track_embeddings.npy", embeddings)
    (d / "embedding_track_ids.json").write_text(json.dumps(track_ids), encoding="utf-8")
    logger.info("Track embeddings saved: %d tracks", len(track_ids))


def load_embeddings() -> tuple[np.ndarray, list[int]] | None:
    """Load embeddings. Returns None if not found."""
    d = _MODEL_DIR
    emb_path = d / "track_embeddings.npy"
    ids_path = d / "embedding_track_ids.json"
    if not emb_path.exists() or not ids_path.exists():
        return None
    embeddings = np.load(emb_path)
    track_ids = json.loads(ids_path.read_text(encoding="utf-8"))
    return embeddings, track_ids


def save_popularity(scores: dict[int, float]) -> None:
    """Save popularity scores."""
    d = ensure_model_dir()
    (d / "popularity_scores.json").write_text(
        json.dumps({str(k): v for k, v in scores.items()}), encoding="utf-8"
    )


def load_popularity() -> dict[int, float] | None:
    d = _MODEL_DIR
    p = d / "popularity_scores.json"
    if not p.exists():
        return None
    raw = json.loads(p.read_text(encoding="utf-8"))
    return {int(k): v for k, v in raw.items()}


def model_exists() -> bool:
    """Check if a trained model exists."""
    d = _MODEL_DIR
    return (d / "als_item_factors.npy").exists()
