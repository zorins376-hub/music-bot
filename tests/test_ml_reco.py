"""Tests for ML Recommendations (3.1): model_store, embeddings, scorer, train."""
import json
import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import numpy as np

from recommender.model_store import (
    save_als, load_als,
    save_embeddings, load_embeddings,
    save_popularity, load_popularity,
    model_exists,
)
from recommender.embeddings import build_sessions, train_embeddings
from recommender.scorer import score_tracks


# ── Model Store ─────────────────────────────────────────────────────────

class TestModelStore:
    def test_save_load_als(self, tmp_path):
        with patch("recommender.model_store._MODEL_DIR", tmp_path):
            uf = np.random.rand(10, 64).astype(np.float32)
            itf = np.random.rand(20, 64).astype(np.float32)
            umap = {"1": 0, "2": 1}
            tmap = {"100": 0, "200": 1}
            save_als(uf, itf, umap, tmap)

            result = load_als()
            assert result is not None
            u, i, um, tm = result
            assert u.shape == (10, 64)
            assert i.shape == (20, 64)
            assert um == umap
            assert tm == tmap

    def test_load_als_missing(self, tmp_path):
        with patch("recommender.model_store._MODEL_DIR", tmp_path):
            assert load_als() is None

    def test_save_load_embeddings(self, tmp_path):
        with patch("recommender.model_store._MODEL_DIR", tmp_path):
            emb = np.random.rand(5, 64).astype(np.float32)
            ids = [1, 2, 3, 4, 5]
            save_embeddings(emb, ids)

            result = load_embeddings()
            assert result is not None
            e, i = result
            assert e.shape == (5, 64)
            assert i == ids

    def test_save_load_popularity(self, tmp_path):
        with patch("recommender.model_store._MODEL_DIR", tmp_path):
            scores = {1: 1.0, 2: 0.5, 3: 0.1}
            save_popularity(scores)
            loaded = load_popularity()
            assert loaded is not None
            assert loaded[1] == 1.0
            assert loaded[3] == 0.1

    def test_model_exists(self, tmp_path):
        with patch("recommender.model_store._MODEL_DIR", tmp_path):
            assert not model_exists()
            np.save(tmp_path / "als_item_factors.npy", np.array([1]))
            assert model_exists()


# ── Embeddings ──────────────────────────────────────────────────────────

class TestEmbeddings:
    def test_build_sessions_basic(self):
        from datetime import datetime, timedelta
        now = datetime.now()
        plays = [
            (1, 100, now),
            (1, 200, now + timedelta(minutes=5)),
            (1, 300, now + timedelta(minutes=10)),
            # Gap > 30 min → new session
            (1, 400, now + timedelta(hours=1)),
            (1, 500, now + timedelta(hours=1, minutes=5)),
            # New user
            (2, 100, now),
            (2, 200, now + timedelta(minutes=5)),
        ]
        sessions = build_sessions(plays)
        assert len(sessions) == 3
        assert sessions[0] == ["100", "200", "300"]
        assert sessions[1] == ["400", "500"]
        assert sessions[2] == ["100", "200"]

    def test_build_sessions_single_track_ignored(self):
        from datetime import datetime
        now = datetime.now()
        plays = [(1, 100, now)]
        sessions = build_sessions(plays)
        assert len(sessions) == 0

    def test_train_embeddings_insufficient_data(self):
        sessions = [["1", "2"]]  # Only 1 session, need 10
        result = train_embeddings(sessions)
        assert result is None


# ── Scorer ──────────────────────────────────────────────────────────────

class TestScorer:
    def test_score_with_no_models(self, tmp_path):
        with patch("recommender.scorer.load_als", return_value=None), \
             patch("recommender.scorer.load_embeddings", return_value=None), \
             patch("recommender.scorer.load_popularity", return_value=None):
            result = score_tracks(
                user_id=1,
                candidate_track_ids=[10, 20, 30],
                listened_ids=set(),
                track_artists={10: "A", 20: "B", 30: "C"},
                limit=3,
            )
            # All scores are 0, so order is arbitrary but all should be present
            assert len(result) == 3

    def test_score_filters_listened(self):
        with patch("recommender.scorer.load_als", return_value=None), \
             patch("recommender.scorer.load_embeddings", return_value=None), \
             patch("recommender.scorer.load_popularity", return_value=None):
            result = score_tracks(
                user_id=1,
                candidate_track_ids=[10, 20, 30],
                listened_ids={10, 20},
                track_artists={10: "A", 20: "B", 30: "C"},
                limit=3,
            )
            assert result == [30]

    def test_score_with_popularity(self):
        pop = {10: 0.3, 20: 0.9, 30: 0.1}
        with patch("recommender.scorer.load_als", return_value=None), \
             patch("recommender.scorer.load_embeddings", return_value=None), \
             patch("recommender.scorer.load_popularity", return_value=pop):
            result = score_tracks(
                user_id=1,
                candidate_track_ids=[10, 20, 30],
                listened_ids=set(),
                track_artists={10: "A", 20: "B", 30: "C"},
                limit=3,
            )
            # Track 20 has highest popularity → should be first
            assert result[0] == 20

    def test_diversity_filter(self):
        pop = {i: 1.0 - i * 0.01 for i in range(1, 11)}
        artists = {i: "Same Artist" for i in range(1, 11)}
        with patch("recommender.scorer.load_als", return_value=None), \
             patch("recommender.scorer.load_embeddings", return_value=None), \
             patch("recommender.scorer.load_popularity", return_value=pop):
            result = score_tracks(
                user_id=1,
                candidate_track_ids=list(range(1, 11)),
                listened_ids=set(),
                track_artists=artists,
                limit=10,
            )
            # MAX_PER_ARTIST = 3, so only 3 tracks from same artist
            assert len(result) == 3

    def test_score_with_als(self):
        # Create fake ALS model
        uf = np.zeros((2, 4), dtype=np.float32)
        itf = np.zeros((3, 4), dtype=np.float32)
        uf[0] = [1, 0, 0, 0]
        itf[0] = [0.5, 0, 0, 0]  # track 10 → score 0.5
        itf[1] = [1.0, 0, 0, 0]  # track 20 → score 1.0
        itf[2] = [0.1, 0, 0, 0]  # track 30 → score 0.1
        als_data = (uf, itf, {"1": 0}, {"10": 0, "20": 1, "30": 2})

        with patch("recommender.scorer.load_als", return_value=als_data), \
             patch("recommender.scorer.load_embeddings", return_value=None), \
             patch("recommender.scorer.load_popularity", return_value=None):
            result = score_tracks(
                user_id=1,
                candidate_track_ids=[10, 20, 30],
                listened_ids=set(),
                track_artists={10: "A", 20: "B", 30: "C"},
                limit=3,
            )
            # Track 20 has highest ALS score
            assert result[0] == 20
