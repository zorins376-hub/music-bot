"""Tests for voice_chat voting and multi-group support."""
import pytest
from unittest.mock import AsyncMock

from streamer.voice_chat import vote, _reset_votes, _votes, _SKIP_THRESHOLD


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
