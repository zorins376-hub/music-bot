"""ML Recommendation Configuration.

Provides ScorerWeights and MLConfig helpers for accessing ML settings.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ScorerWeights:
    """Weights for hybrid recommendation scoring.
    
    Components:
    - als: Collaborative filtering signal from ALS model
    - emb: Content-based signal from track embeddings
    - pop: Popularity signal (downloads)
    - fresh: Freshness bonus for new tracks (<7 days)
    - time: Time-of-day matching bonus
    """
    als: float = 0.40
    emb: float = 0.25
    pop: float = 0.15
    fresh: float = 0.10
    time: float = 0.10
    
    def __post_init__(self):
        total = self.als + self.emb + self.pop + self.fresh + self.time
        if abs(total - 1.0) > 0.01:
            # Normalize to sum=1
            self.als /= total
            self.emb /= total
            self.pop /= total
            self.fresh /= total
            self.time /= total


@dataclass
class DiversityConfig:
    """Diversity enforcement settings."""
    max_per_artist: int = 2  # Max tracks per artist in top-N
    max_per_genre: int = 3   # Max tracks per genre in top-N


@dataclass
class ALSConfig:
    """ALS model hyperparameters."""
    factors: int = 64
    iterations: int = 15
    regularization: float = 0.01
    use_gpu: bool = False  # CPU only for VPS


@dataclass
class Word2VecConfig:
    """Word2Vec model hyperparameters."""
    vector_size: int = 64
    window: int = 5
    min_count: int = 2
    sg: int = 1  # Skip-gram
    epochs: int = 10
    workers: int = 2


class MLConfig:
    """Singleton accessor for ML configuration from bot settings.
    
    Usage:
        from recommender.config import MLConfig
        cfg = MLConfig.get()
        if cfg.enabled:
            weights = cfg.scorer_weights
    """
    
    _instance: "MLConfig | None" = None
    
    def __init__(self):
        from bot.config import settings
        self._settings = settings
    
    @classmethod
    def get(cls) -> "MLConfig":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @property
    def enabled(self) -> bool:
        return self._settings.ML_ENABLED
    
    @property
    def ab_test_enabled(self) -> bool:
        return self._settings.ML_AB_TEST_ENABLED
    
    @property
    def model_dir(self) -> Path:
        return Path(self._settings.ML_MODEL_DIR)
    
    @property
    def retrain_hour(self) -> int:
        return self._settings.ML_RETRAIN_HOUR
    
    @property
    def min_interactions(self) -> int:
        return self._settings.ML_MIN_INTERACTIONS
    
    @property
    def min_users(self) -> int:
        return self._settings.ML_MIN_USERS
    
    @property
    def session_gap_minutes(self) -> int:
        return self._settings.ML_SESSION_GAP_MINUTES
    
    @property
    def cold_start_threshold(self) -> int:
        return self._settings.ML_COLD_START_THRESHOLD
    
    @property
    def cache_ttl(self) -> int:
        return self._settings.ML_RECO_CACHE_TTL
    
    @property
    def scorer_weights(self) -> ScorerWeights:
        """Returns scorer weights from settings."""
        return ScorerWeights(
            als=self._settings.ML_SCORER_W_ALS,
            emb=self._settings.ML_SCORER_W_EMB,
            pop=self._settings.ML_SCORER_W_POP,
            fresh=self._settings.ML_SCORER_W_FRESH,
            time=self._settings.ML_SCORER_W_TIME,
        )
    
    @property
    def diversity(self) -> DiversityConfig:
        """Returns diversity config from settings."""
        return DiversityConfig(
            max_per_artist=self._settings.ML_MAX_PER_ARTIST,
            max_per_genre=self._settings.ML_MAX_PER_GENRE,
        )
    
    @property
    def als_config(self) -> ALSConfig:
        """Returns ALS hyperparameters from settings."""
        return ALSConfig(
            factors=self._settings.ML_ALS_FACTORS,
            iterations=self._settings.ML_ALS_ITERATIONS,
            regularization=self._settings.ML_ALS_REGULARIZATION,
        )
    
    @property
    def w2v_config(self) -> Word2VecConfig:
        """Returns Word2Vec hyperparameters from settings."""
        return Word2VecConfig(
            vector_size=self._settings.ML_W2V_VECTOR_SIZE,
            window=self._settings.ML_W2V_WINDOW,
            epochs=self._settings.ML_W2V_EPOCHS,
        )


# Action weights for implicit feedback matrix
ACTION_WEIGHTS = {
    "play": 1.0,
    "like": 2.0,
    "dislike": -1.0,
    "skip": 0.3,
}

# Listen ratio multipliers
FULL_LISTEN_MULTIPLIER = 1.5    # listen_duration / duration > 0.8
PARTIAL_LISTEN_MULTIPLIER = 0.5  # listen_duration / duration < 0.3


# Backward-compatible singleton export used across recommender modules
ml_config = MLConfig.get()
