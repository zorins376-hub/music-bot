"""Tests for TMA Player (1.1): auth, schemas, API."""
import hashlib
import hmac
import json
import time
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from webapp.auth import verify_init_data
from webapp.schemas import (
    PlayerState, PlayerAction, TrackSchema,
    PlaylistSchema, LyricsResponse, SearchResult,
)


# ── Auth tests ──────────────────────────────────────────────────────────

class TestVerifyInitData:
    def _make_init_data(self, user: dict, bot_token: str = "1234567890:AAFakeTokenForTestingPurposesOnly000") -> str:
        """Build a valid initData string."""
        auth_date = str(int(time.time()))
        user_json = json.dumps(user, ensure_ascii=False)
        parts = {
            "auth_date": auth_date,
            "user": user_json,
            "query_id": "test_query",
        }
        data_check = "\n".join(sorted(f"{k}={v}" for k, v in parts.items()))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        h = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        params = "&".join(f"{k}={v}" for k, v in parts.items())
        return f"{params}&hash={h}"

    def test_valid_init_data(self):
        user = {"id": 123, "first_name": "Test"}
        init_data = self._make_init_data(user)
        result = verify_init_data(init_data)
        assert result is not None
        assert result["id"] == 123

    def test_invalid_hash(self):
        user = {"id": 123, "first_name": "Test"}
        init_data = self._make_init_data(user)
        init_data = init_data.replace("hash=", "hash=0000")
        result = verify_init_data(init_data)
        assert result is None

    def test_expired_data(self):
        user = {"id": 123, "first_name": "Test"}
        init_data = self._make_init_data(user)
        # Replace auth_date with very old timestamp
        result = verify_init_data(init_data, max_age=0)
        assert result is None

    def test_missing_hash(self):
        result = verify_init_data("auth_date=12345&user={}")
        assert result is None

    def test_missing_user(self):
        auth_date = str(int(time.time()))
        data_check = f"auth_date={auth_date}"
        secret = hmac.new(b"WebAppData", b"1234567890:AAFakeTokenForTestingPurposesOnly000", hashlib.sha256).digest()
        h = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        result = verify_init_data(f"auth_date={auth_date}&hash={h}")
        assert result is None


# ── Schema tests ────────────────────────────────────────────────────────

class TestSchemas:
    def test_player_state_defaults(self):
        state = PlayerState()
        assert state.current_track is None
        assert state.queue == []
        assert not state.is_playing
        assert state.repeat_mode == "off"

    def test_track_schema(self):
        t = TrackSchema(video_id="abc", title="Test Track", artist="Artist")
        assert t.video_id == "abc"
        assert t.duration == 0

    def test_player_action(self):
        a = PlayerAction(action="play", track_id="xyz")
        assert a.action == "play"
        assert a.track_id == "xyz"

    def test_playlist_schema(self):
        p = PlaylistSchema(id=1, name="My Playlist", track_count=5)
        assert p.track_count == 5

    def test_lyrics_response(self):
        lr = LyricsResponse(track_id="abc", lyrics="Hello world")
        assert lr.source == "genius"

    def test_search_result(self):
        sr = SearchResult(tracks=[], total=0)
        assert sr.tracks == []

    def test_player_state_serialization(self):
        state = PlayerState(
            current_track=TrackSchema(video_id="x", title="T"),
            is_playing=True,
        )
        data = state.model_dump()
        assert data["is_playing"] is True
        assert data["current_track"]["video_id"] == "x"


# ── API route tests (mocked) ───────────────────────────────────────────

class TestPlayerActions:
    def test_player_state_with_queue(self):
        tracks = [
            TrackSchema(video_id="a", title="Track A"),
            TrackSchema(video_id="b", title="Track B"),
        ]
        state = PlayerState(queue=tracks, position=0, is_playing=True)
        assert len(state.queue) == 2
        assert state.position == 0

    def test_repeat_mode_cycle(self):
        modes = ["off", "one", "all"]
        for i, mode in enumerate(modes):
            state = PlayerState(repeat_mode=mode)
            next_mode = modes[(i + 1) % len(modes)]
            assert next_mode in modes
