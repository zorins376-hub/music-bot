"""Tests for Bot Fleet / Sharding (5.2): dispatcher, node_manager."""
import hashlib
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.dispatcher_bot import _route_user, _NODE_BOTS


# ── Dispatcher routing ──────────────────────────────────────────────────

class TestRouting:
    def test_route_user_empty_nodes(self):
        """With no nodes configured, should return 0."""
        _NODE_BOTS.clear()
        assert _route_user(123) == 0

    def test_route_user_deterministic(self):
        """Same user always routes to same node."""
        _NODE_BOTS.clear()
        _NODE_BOTS.extend([
            {"token": "a", "username": "bot1", "id": 1},
            {"token": "b", "username": "bot2", "id": 2},
            {"token": "c", "username": "bot3", "id": 3},
        ])
        node1 = _route_user(12345)
        node2 = _route_user(12345)
        assert node1 == node2

    def test_route_user_distribution(self):
        """Users should distribute across nodes."""
        _NODE_BOTS.clear()
        _NODE_BOTS.extend([
            {"token": "a", "username": "bot1", "id": 1},
            {"token": "b", "username": "bot2", "id": 2},
        ])
        results = set()
        for uid in range(1, 100):
            results.add(_route_user(uid))
        # Both nodes should get some users
        assert len(results) == 2

    def test_route_user_uses_sha256(self):
        _NODE_BOTS.clear()
        _NODE_BOTS.extend([
            {"token": "a", "username": "bot1", "id": 1},
            {"token": "b", "username": "bot2", "id": 2},
        ])
        uid = 42
        expected = int(hashlib.sha256(str(uid).encode()).hexdigest(), 16) % 2
        assert _route_user(uid) == expected


# ── Node Manager ────────────────────────────────────────────────────────

class TestNodeManager:
    @pytest.mark.asyncio
    async def test_register_and_list(self):
        import fakeredis.aioredis as fakeredis
        fake = fakeredis.FakeRedis(decode_responses=True)

        with patch("bot.services.node_manager._redis", return_value=fake):
            from bot.services.node_manager import register_node, list_nodes
            await register_node("node-1")
            nodes = await list_nodes()
            assert any(n.get("node_id") == "node-1" for n in nodes)

    @pytest.mark.asyncio
    async def test_heartbeat(self):
        import fakeredis.aioredis as fakeredis
        fake = fakeredis.FakeRedis(decode_responses=True)

        with patch("bot.services.node_manager._redis", return_value=fake):
            from bot.services.node_manager import heartbeat
            await heartbeat("node-1", user_count=42)
            raw = await fake.get("node:node-1:status")
            data = json.loads(raw)
            assert data["user_count"] == 42
            assert data["alive"] is True

    @pytest.mark.asyncio
    async def test_deregister(self):
        import fakeredis.aioredis as fakeredis
        fake = fakeredis.FakeRedis(decode_responses=True)

        with patch("bot.services.node_manager._redis", return_value=fake):
            from bot.services.node_manager import register_node, deregister_node
            await register_node("node-x")
            await deregister_node("node-x")
            assert await fake.get("node:node-x:status") is None

    @pytest.mark.asyncio
    async def test_migrate_node(self):
        import fakeredis.aioredis as fakeredis
        fake = fakeredis.FakeRedis(decode_responses=True)

        with patch("bot.services.node_manager._redis", return_value=fake):
            from bot.services.node_manager import register_node, migrate_node, set_user_route, get_user_route

            await register_node("node-1")
            await register_node("node-2")

            # Route some users to node-2
            await set_user_route(100, "node-2")
            await set_user_route(200, "node-2")
            await set_user_route(300, "node-1")

            # Migrate node-2 users
            moved = await migrate_node("node-2")
            assert moved == 2

            # Migrated users should now be on node-1
            route100 = await get_user_route(100)
            assert route100 == "node-1"
            route300 = await get_user_route(300)
            assert route300 == "node-1"  # unchanged

    @pytest.mark.asyncio
    async def test_set_get_user_route(self):
        import fakeredis.aioredis as fakeredis
        fake = fakeredis.FakeRedis(decode_responses=True)

        with patch("bot.services.node_manager._redis", return_value=fake):
            from bot.services.node_manager import set_user_route, get_user_route
            await set_user_route(42, "node-3")
            assert await get_user_route(42) == "node-3"
            assert await get_user_route(999) is None

    @pytest.mark.asyncio
    async def test_get_alive_nodes(self):
        import fakeredis.aioredis as fakeredis
        fake = fakeredis.FakeRedis(decode_responses=True)

        with patch("bot.services.node_manager._redis", return_value=fake):
            from bot.services.node_manager import register_node, get_alive_nodes
            await register_node("alive-1")
            await register_node("alive-2")
            alive = await get_alive_nodes()
            assert "alive-1" in alive
            assert "alive-2" in alive
