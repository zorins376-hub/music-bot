"""
scorer.py — Hybrid recommendation scorer (ML-ядро).

5-component scoring:
- ALS collaborative (40%)
- Embedding similarity (25%)
- Popularity (15%)
- Freshness (10%)
- Time-of-day (10%)

With diversity filter: max 2 tracks/artist, max 3 tracks/genre.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import numpy as np

from recommender.config import ml_config
from recommender.model_store import load_als, load_embeddings, load_popularity, model_store

if TYPE_CHECKING:
    from recommender.embeddings import TrackEmbeddings

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Data Classes
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class ScoredTrack:
    """Single scored track with breakdown."""
    track_id: int
    source_id: str  # e.g. "vk_123456" or "yt_abc"
    score: float
    components: dict[str, float] = field(default_factory=dict)
    algo: str = "hybrid"
    artist: str = ""
    genre: str = ""


@dataclass
class ScoringContext:
    """Context for scoring session."""
    current_hour_utc: int = field(default_factory=lambda: datetime.now(timezone.utc).hour)
    recent_source_ids: list[str] = field(default_factory=list)  # for embedding (source_id strings)
    listened_ids: set[int] = field(default_factory=set)          # all-time history (track_ids)
    preferred_hours: list[int] | None = None                     # user's active hours


# ═══════════════════════════════════════════════════════════════════════════
# HybridScorer
# ═══════════════════════════════════════════════════════════════════════════


class HybridScorer:
    """
    Multi-signal scorer for track recommendations.
    
    Uses ALS collaborative filtering + Word2Vec embeddings + popularity + freshness + time.
    """

    def __init__(self, embeddings: TrackEmbeddings | None = None):
        self.config = ml_config
        self.weights = self.config.scorer
        self.diversity = self.config.diversity
        self._embeddings = embeddings

    @property
    def embeddings(self) -> TrackEmbeddings | None:
        """Lazy load embeddings if not provided."""
        if self._embeddings is None:
            try:
                from recommender.embeddings import TrackEmbeddings
                self._embeddings = TrackEmbeddings()
            except Exception as e:
                logger.warning(f"Could not load embeddings: {e}")
        return self._embeddings

    def score(
        self,
        user_id: int,
        candidates: list[dict],
        context: ScoringContext | None = None,
    ) -> list[ScoredTrack]:
        """
        Score candidate tracks using 5-component hybrid approach.
        
        Args:
            user_id: target user
            candidates: list of dicts with track metadata:
                - id: int (track_id)
                - source_id: str (e.g. "vk_123456")
                - artist: str
                - genre: str
                - play_count: int (optional, for popularity)
                - added_at: datetime (optional, for freshness)
            context: scoring context with session info
            
        Returns:
            List of ScoredTrack sorted by score descending
        """
        if not candidates:
            return []

        ctx = context or ScoringContext()
        results: list[ScoredTrack] = []

        # Get ALS scores for all candidates in batch
        als_scores = self._get_als_scores(user_id, [c["id"] for c in candidates])
        
        # Get embedding similarity if available (using source_ids)
        embed_scores = self._get_embedding_scores(ctx.recent_source_ids, candidates)

        # Normalize play counts for popularity
        max_plays = max((c.get("play_count", 0) for c in candidates), default=1) or 1

        for c in candidates:
            track_id = c["id"]
            
            # Skip if in listened history
            if track_id in ctx.listened_ids:
                continue

            components: dict[str, float] = {}

            # ── ALS score ────────────────────────────────────────────────
            als_raw = als_scores.get(track_id, 0.0)
            components["als"] = als_raw

            # ── Embedding similarity ─────────────────────────────────────
            embed_raw = embed_scores.get(track_id, 0.0)
            components["embed"] = embed_raw

            # ── Popularity (normalized) ──────────────────────────────────
            pop_raw = c.get("play_count", 0) / max_plays
            components["popularity"] = pop_raw

            # ── Freshness (decay over 30 days) ───────────────────────────
            added_at = c.get("added_at")
            if added_at:
                days_old = (datetime.now(timezone.utc) - added_at).days
                freshness = max(0, 1 - days_old / 30)
            else:
                freshness = 0.5  # default if unknown
            components["freshness"] = freshness

            # ── Time-of-day boost ────────────────────────────────────────
            time_boost = 0.0
            if ctx.preferred_hours:
                if ctx.current_hour_utc in ctx.preferred_hours:
                    time_boost = 1.0
                elif any(abs(ctx.current_hour_utc - h) <= 1 for h in ctx.preferred_hours):
                    time_boost = 0.5
            components["time"] = time_boost

            # ── Weighted sum ─────────────────────────────────────────────
            final_score = (
                self.weights.als * components["als"]
                + self.weights.embedding * components["embed"]
                + self.weights.popularity * components["popularity"]
                + self.weights.freshness * components["freshness"]
                + self.weights.time * components["time"]
            )

            results.append(ScoredTrack(
                track_id=track_id,
                source_id=c.get("source_id", ""),
                score=final_score,
                components=components,
                algo="hybrid",
                artist=c.get("artist", ""),
                genre=c.get("genre", ""),
            ))

        # Sort by score descending
        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def _get_als_scores(self, user_id: int, track_ids: list[int]) -> dict[int, float]:
        """Get ALS scores for tracks from ModelStore."""
        scores: dict[int, float] = {}
        
        if not model_store.is_ready:
            return scores

        try:
            # Get user's matrix index
            user_idx = model_store.get_user_idx(user_id)
            if user_idx is None:
                return scores
            
            # Get user vector and compute dot product with all item factors
            user_factors = model_store.get_user_factors()
            item_factors = model_store.get_item_factors()
            
            if user_factors is None or item_factors is None:
                return scores
            
            user_vec = user_factors[user_idx]
            
            # Score each candidate track
            for tid in track_ids:
                track_idx = model_store.get_track_idx(tid)
                if track_idx is not None:
                    score = float(np.dot(user_vec, item_factors[track_idx]))
                    scores[tid] = max(0, score)  # clamp negative
        except Exception as e:
            logger.warning(f"ALS scoring failed: {e}")

        return scores

    def _get_embedding_scores(
        self, recent_source_ids: list[str], candidates: list[dict]
    ) -> dict[int, float]:
        """Get embedding similarity scores using user's recent listening."""
        scores: dict[int, float] = {}
        
        if not self.embeddings or not recent_source_ids:
            return scores

        try:
            # Build user taste vector from recent tracks' source_ids
            user_vec = self.embeddings.get_session_vector(recent_source_ids[-50:])
            if user_vec is None:
                return scores

            for c in candidates:
                tid = c["id"]
                source_id = c.get("source_id", "")
                if not source_id:
                    continue
                track_vec = self.embeddings.get_track_vector(source_id)
                if track_vec is not None:
                    sim = self.embeddings.cosine_similarity_vectors(user_vec, track_vec)
                    scores[tid] = max(0, sim)  # clamp negative
        except Exception as e:
            logger.warning(f"Embedding scoring failed: {e}")

        return scores

    def apply_diversity(self, tracks: list[ScoredTrack], limit: int = 10) -> list[ScoredTrack]:
        """
        Apply diversity filter to scored tracks.
        
        Rules:
        - Max N tracks per artist
        - Max M tracks per genre
        """
        artist_count: Counter = Counter()
        genre_count: Counter = Counter()
        result: list[ScoredTrack] = []

        for track in tracks:
            artist = track.artist.lower() if track.artist else "unknown"
            genre = track.genre.lower() if track.genre else "unknown"

            # Check artist limit
            if artist_count[artist] >= self.diversity.max_per_artist:
                continue
            
            # Check genre limit
            if genre_count[genre] >= self.diversity.max_per_genre:
                continue

            artist_count[artist] += 1
            genre_count[genre] += 1
            result.append(track)

            if len(result) >= limit:
                break

        return result


# ═══════════════════════════════════════════════════════════════════════════
# Convenience Functions (backward compat)
# ═══════════════════════════════════════════════════════════════════════════


def score_tracks(
    user_id: int,
    candidate_track_ids: list[int],
    listened_ids: set[int],
    track_artists: dict[int, str],
    limit: int = 10,
) -> list[int]:
    """
    Legacy function for backward compatibility.
    
    Score and rank candidate tracks using hybrid ML approach.
    """
    candidate_ids = [tid for tid in candidate_track_ids if tid not in listened_ids]
    if not candidate_ids:
        return []

    als_data = load_als()
    _ = load_embeddings()
    popularity = load_popularity() or {}

    als_scores: dict[int, float] = {tid: 0.0 for tid in candidate_ids}
    if als_data is not None:
        user_factors, item_factors, user_id_map, track_id_map = als_data
        user_idx = user_id_map.get(str(user_id), user_id_map.get(user_id))
        if user_idx is not None and 0 <= int(user_idx) < len(user_factors):
            user_vec = user_factors[int(user_idx)]
            for tid in candidate_ids:
                item_idx = track_id_map.get(str(tid), track_id_map.get(tid))
                if item_idx is None:
                    continue
                idx = int(item_idx)
                if 0 <= idx < len(item_factors):
                    als_scores[tid] = float(np.dot(user_vec, item_factors[idx]))

    ranked = sorted(
        candidate_ids,
        key=lambda tid: (als_scores.get(tid, 0.0), popularity.get(tid, 0.0)),
        reverse=True,
    )

    max_per_artist = 3
    artist_count: Counter[str] = Counter()
    result: list[int] = []
    for tid in ranked:
        artist = (track_artists.get(tid) or "unknown").lower()
        if artist_count[artist] >= max_per_artist:
            continue
        artist_count[artist] += 1
        result.append(tid)
        if len(result) >= limit:
            break

    return result


def score_candidates(
    user_id: int,
    candidates: list[dict],
    context: ScoringContext | None = None,
    limit: int = 10,
) -> list[ScoredTrack]:
    """
    Main entry point for hybrid scoring.
    
    Args:
        user_id: target user
        candidates: list of track dicts (id, source_id, artist, genre, play_count, added_at)
        context: optional scoring context
        limit: max results after diversity filter
        
    Returns:
        List of ScoredTrack with scores and component breakdown
    """
    scorer = HybridScorer()
    scored = scorer.score(user_id, candidates, context)
    return scorer.apply_diversity(scored, limit=limit)
