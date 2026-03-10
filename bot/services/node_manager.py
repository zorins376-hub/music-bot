"""
node_manager.py — Redis-based node health + migration for Bot Fleet (5.2).

Each node bot sends heartbeats every 30 seconds:
  Redis key: node:{node_id}:status = JSON {alive, user_count, last_heartbeat}

Migration: when a node is banned/dead, redistribute its users' routing
to remaining alive nodes.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL = 30  # seconds
_NODE_TTL = 90  # consider dead if no heartbeat for 90s


async def _redis():
    from bot.services.cache import cache
    return cache.redis


def _status_key(node_id: str) -> str:
    return f"node:{node_id}:status"


def _routing_key() -> str:
    return "fleet:user_routing"


async def register_node(node_id: str) -> None:
    """Register this node in Redis."""
    r = await _redis()
    data = json.dumps({
        "node_id": node_id,
        "alive": True,
        "user_count": 0,
        "last_heartbeat": datetime.now(timezone.utc).isoformat(),
        "registered_at": datetime.now(timezone.utc).isoformat(),
    })
    await r.setex(_status_key(node_id), _NODE_TTL, data)
    logger.info("Node %s registered", node_id)


async def heartbeat(node_id: str, user_count: int = 0) -> None:
    """Send heartbeat for this node."""
    r = await _redis()
    data = json.dumps({
        "node_id": node_id,
        "alive": True,
        "user_count": user_count,
        "last_heartbeat": datetime.now(timezone.utc).isoformat(),
    })
    await r.setex(_status_key(node_id), _NODE_TTL, data)


async def deregister_node(node_id: str) -> None:
    """Remove a node from the pool."""
    r = await _redis()
    await r.delete(_status_key(node_id))
    logger.info("Node %s deregistered", node_id)


async def list_nodes() -> list[dict]:
    """List all known nodes and their status."""
    r = await _redis()
    keys = []
    async for key in r.scan_iter(match="node:*:status"):
        keys.append(key)

    nodes = []
    for key in keys:
        raw = await r.get(key)
        if raw:
            data = json.loads(raw)
            nodes.append(data)
        else:
            # Key expired — node is dead
            node_id = key.decode().split(":")[1] if isinstance(key, bytes) else key.split(":")[1]
            nodes.append({"node_id": node_id, "alive": False, "user_count": 0, "last_heartbeat": "expired"})

    return sorted(nodes, key=lambda n: n.get("node_id", ""))


async def get_alive_nodes() -> list[str]:
    """Get list of alive node IDs."""
    nodes = await list_nodes()
    return [n["node_id"] for n in nodes if n.get("alive")]


async def migrate_node(dead_node_id: str) -> int:
    """
    Migrate users routed to a dead node to remaining alive nodes.

    Returns number of users migrated.
    """
    r = await _redis()
    routing_key = _routing_key()

    alive = await get_alive_nodes()
    alive = [n for n in alive if n != dead_node_id]
    if not alive:
        logger.error("No alive nodes to migrate to!")
        return 0

    # Get all user routings
    all_routes = await r.hgetall(routing_key)
    migrated = 0

    for user_id_bytes, node_bytes in all_routes.items():
        node = node_bytes.decode() if isinstance(node_bytes, bytes) else node_bytes
        if node == dead_node_id:
            # Round-robin to alive nodes
            new_node = alive[migrated % len(alive)]
            await r.hset(routing_key, user_id_bytes, new_node)
            migrated += 1

    # Remove dead node
    await deregister_node(dead_node_id)

    logger.info("Migrated %d users from %s to %s", migrated, dead_node_id, alive)
    return migrated


async def set_user_route(user_id: int, node_id: str) -> None:
    """Set explicit routing for a user to a specific node."""
    r = await _redis()
    await r.hset(_routing_key(), str(user_id), node_id)


async def get_user_route(user_id: int) -> str | None:
    """Get the node a user is routed to."""
    r = await _redis()
    result = await r.hget(_routing_key(), str(user_id))
    if result:
        return result.decode() if isinstance(result, bytes) else result
    return None


async def start_heartbeat_loop(node_id: str) -> None:
    """Background task: send heartbeats every _HEARTBEAT_INTERVAL seconds."""
    async def _loop():
        while True:
            try:
                # Count active users (rough estimate from DB)
                try:
                    from sqlalchemy import func, select
                    from bot.models.base import async_session
                    from bot.models.user import User
                    from datetime import timedelta
                    async with async_session() as session:
                        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                        r = await session.execute(
                            select(func.count(User.id)).where(User.last_active >= cutoff)
                        )
                        user_count = r.scalar() or 0
                except Exception:
                    user_count = 0

                await heartbeat(node_id, user_count)
            except Exception as e:
                logger.error("Heartbeat error: %s", e)
            await asyncio.sleep(_HEARTBEAT_INTERVAL)

    asyncio.create_task(_loop())
