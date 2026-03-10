"""
scorer.py — Hybrid recommendation scorer.

Score = ALS_score × 0.5 + Embedding_similarity × 0.3 + Popularity × 0.2

With diversity filter: max 3 tracks per artist in final results.
"""
import logging
from collections import Counter

import numpy as np

from recommender.model_store import load_als, load_embeddings, load_popularity

logger = logging.getLogger(__name__)

# Weights
W_ALS = 0.5
W_EMBED = 0.3
W_POP = 0.2

# Max tracks per artist in results
MAX_PER_ARTIST = 3


def score_tracks(
    user_id: int,
    candidate_track_ids: list[int],
    listened_ids: set[int],
    track_artists: dict[int, str],
    limit: int = 10,
) -> list[int]:
    """
    Score and rank candidate tracks using hybrid ML approach.

    Args:
        user_id: target user
        candidate_track_ids: pool of tracks to score
        listened_ids: tracks user already played (exclude)
        track_artists: {track_id: artist_name} for diversity filter
        limit: max results

    Returns:
        Sorted list of track IDs (best first)
    """
    als_data = load_als()
    embed_data = load_embeddings()
    pop_data = load_popularity()

    # Filter candidates: remove already listened
    candidates = [tid for tid in candidate_track_ids if tid not in listened_ids]
    if not candidates:
        return []

    scores: dict[int, float] = {tid: 0.0 for tid in candidates}

    # ── ALS score ────────────────────────────────────────────────────────
    if als_data:
        user_factors, item_factors, user_map, track_map = als_data
        user_key = str(user_id)
        if user_key in user_map:
            u_idx = user_map[user_key]
            u_vec = user_factors[u_idx]
            for tid in candidates:
                t_key = str(tid)
                if t_key in track_map:
                    t_idx = track_map[t_key]
                    als_score = float(np.dot(u_vec, item_factors[t_idx]))
                    scores[tid] += W_ALS * als_score

    # ── Embedding similarity ─────────────────────────────────────────────
    if embed_data:
        embeddings, embed_track_ids = embed_data
        embed_map = {tid: i for i, tid in enumerate(embed_track_ids)}

        # User profile = mean of recently listened track embeddings
        user_embeds = []
        for lid in list(listened_ids)[-50:]:
            if lid in embed_map:
                user_embeds.append(embeddings[embed_map[lid]])

        if user_embeds:
            user_vec = np.mean(user_embeds, axis=0)
            norm = np.linalg.norm(user_vec)
            if norm > 0:
                user_vec /= norm
            for tid in candidates:
                if tid in embed_map:
                    sim = float(np.dot(user_vec, embeddings[embed_map[tid]]))
                    scores[tid] += W_EMBED * max(0, sim)

    # ── Popularity score ─────────────────────────────────────────────────
    if pop_data:
        for tid in candidates:
            if tid in pop_data:
                scores[tid] += W_POP * pop_data[tid]

    # ── Sort by score ────────────────────────────────────────────────────
    ranked = sorted(candidates, key=lambda tid: scores[tid], reverse=True)

    # ── Diversity filter: ≤ MAX_PER_ARTIST ───────────────────────────────
    artist_count: Counter = Counter()
    result: list[int] = []
    for tid in ranked:
        artist = track_artists.get(tid, "unknown")
        if artist_count[artist] >= MAX_PER_ARTIST:
            continue
        artist_count[artist] += 1
        result.append(tid)
        if len(result) >= limit:
            break

    return result
