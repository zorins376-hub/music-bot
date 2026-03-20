"""Tests for voice_chat voting and multi-group support."""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock

from streamer.voice_chat import (
    vote,
    _reset_votes,
    _votes,
    _SKIP_THRESHOLD,
    _handle_radio_command,
    _listen_for_radio_commands,
    _run_radio_command_listener,
    _sync_current_track_state,
)


class _FakePubSub:
    def __init__(self, messages):
        self._messages = messages
        self.closed = False
        self.subscriptions: list[str] = []

    async def subscribe(self, *channels):
        self.subscriptions.extend(channels)

    async def listen(self):
        for message in self._messages:
            yield message

    async def close(self):
        self.closed = True


class _CrashingPubSub(_FakePubSub):
    async def listen(self):
        if False:
            yield None
        raise RuntimeError("redis hiccup")


class _RedisWithPubsubs:
    def __init__(self, pubsubs):
        self._pubsubs = list(pubsubs)
        self.pubsub_calls = 0

    def pubsub(self):
        self.pubsub_calls += 1
        if not self._pubsubs:
            raise RuntimeError("no more pubsubs")
        return self._pubsubs.pop(0)


class TestVoting:
    def setup_method(self):
        _votes.clear()

    @pytest.mark.asyncio
    async def test_like_vote(self):
        tally = await vote(100, 1, "like")
        assert tally == {"likes": 1, "dislikes": 0}

    @pytest.mark.asyncio
    async def test_dislike_vote(self):
        tally = await vote(100, 1, "dislike")
        assert tally == {"likes": 0, "dislikes": 1}

    @pytest.mark.asyncio
    async def test_vote_switch(self):
        """Switching from like to dislike removes the like."""
        await vote(100, 1, "like")
        tally = await vote(100, 1, "dislike")
        assert tally == {"likes": 0, "dislikes": 1}

    @pytest.mark.asyncio
    async def test_multiple_users(self):
        await vote(100, 1, "like")
        await vote(100, 2, "like")
        tally = await vote(100, 3, "dislike")
        assert tally == {"likes": 2, "dislikes": 1}

    @pytest.mark.asyncio
    async def test_skip_on_threshold(self):
        skip_cb = AsyncMock()
        for i in range(1, _SKIP_THRESHOLD):
            await vote(100, i, "dislike")
        # This vote should trigger skip
        tally = await vote(100, _SKIP_THRESHOLD, "dislike", skip_cb=skip_cb)
        skip_cb.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_skip_below_threshold(self):
        skip_cb = AsyncMock()
        for i in range(1, _SKIP_THRESHOLD):
            await vote(100, i, "dislike", skip_cb=skip_cb)
        skip_cb.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_multi_group_isolation(self):
        """Votes in group 100 don't affect group 200."""
        await vote(100, 1, "like")
        tally = await vote(200, 2, "dislike")
        assert tally == {"likes": 0, "dislikes": 1}
        # group 100 still has its own vote
        assert len(_votes[100]["likes"]) == 1

    def test_reset_votes(self):
        _votes[100]["likes"].add(1)
        _votes[100]["dislikes"].add(2)
        _reset_votes(100)
        assert len(_votes[100]["likes"]) == 0
        assert len(_votes[100]["dislikes"]) == 0

    @pytest.mark.asyncio
    async def test_same_user_one_vote(self):
        """Same user voting twice keeps only one vote."""
        await vote(100, 1, "like")
        await vote(100, 1, "like")
        assert len(_votes[100]["likes"]) == 1


@pytest.mark.asyncio
async def test_handle_radio_command_skip_calls_play_next():
    play_next = AsyncMock()
    clear_current_track = AsyncMock()
    tgcalls = AsyncMock()
    cache = AsyncMock()

    await _handle_radio_command(
        "skip",
        group_id=100,
        tgcalls=tgcalls,
        play_next=play_next,
        clear_current_track=clear_current_track,
        cache=cache,
    )

    play_next.assert_awaited_once()
    clear_current_track.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_radio_command_stop_clears_current_track():
    play_next = AsyncMock()
    clear_current_track = AsyncMock()
    tgcalls = AsyncMock()
    cache = AsyncMock()

    await _handle_radio_command(
        "stop",
        group_id=100,
        tgcalls=tgcalls,
        play_next=play_next,
        clear_current_track=clear_current_track,
        cache=cache,
    )

    tgcalls.leave_call.assert_awaited_once_with(100)
    clear_current_track.assert_awaited_once()


@pytest.mark.asyncio
async def test_listen_for_radio_commands_consumes_skip_and_closes_pubsub():
    play_next = AsyncMock()
    clear_current_track = AsyncMock()
    tgcalls = AsyncMock()
    cache = AsyncMock()
    pubsub = _FakePubSub([
        {"type": "subscribe", "data": 1},
        {"type": "message", "data": "skip"},
    ])

    await _listen_for_radio_commands(
        pubsub,
        group_id=100,
        tgcalls=tgcalls,
        play_next=play_next,
        clear_current_track=clear_current_track,
        cache=cache,
    )

    play_next.assert_awaited_once()
    assert pubsub.closed is True


@pytest.mark.asyncio
async def test_sync_current_track_state_replaces_previous_channel(fake_redis):
    cache = AsyncMock()
    cache.redis = fake_redis
    await fake_redis.set("radio:current:tequila", json.dumps({"video_id": "old"}))

    next_channel = await _sync_current_track_state(
        cache,
        {"video_id": "new", "channel": "sunset", "duration": 42},
        "tequila",
    )

    assert next_channel == "sunset"
    assert await fake_redis.exists("radio:current:tequila") == 0
    assert json.loads(await fake_redis.get("radio:current:sunset"))["video_id"] == "new"


@pytest.mark.asyncio
async def test_sync_current_track_state_clears_previous_on_empty(fake_redis):
    cache = AsyncMock()
    cache.redis = fake_redis
    await fake_redis.set("radio:current:sunset", json.dumps({"video_id": "current"}))

    next_channel = await _sync_current_track_state(cache, None, "sunset")

    assert next_channel is None
    assert await fake_redis.exists("radio:current:sunset") == 0


@pytest.mark.asyncio
async def test_run_radio_command_listener_recovers_after_pubsub_crash():
    play_next = AsyncMock()
    clear_current_track = AsyncMock()
    tgcalls = AsyncMock()
    cache = AsyncMock()
    redis = _RedisWithPubsubs([
        _CrashingPubSub([]),
        _FakePubSub([
            {"type": "subscribe", "data": 1},
            {"type": "message", "data": "skip"},
        ]),
    ])

    task = asyncio.create_task(
        _run_radio_command_listener(
            redis,
            group_id=100,
            tgcalls=tgcalls,
            play_next=play_next,
            clear_current_track=clear_current_track,
            cache=cache,
            reconnect_delay=0,
        )
    )

    for _ in range(20):
        if play_next.await_count:
            break
        await asyncio.sleep(0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    play_next.assert_awaited_once()
    assert redis.pubsub_calls >= 2
