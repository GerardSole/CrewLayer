"""Agent status helpers — mutate DB fields and manage Redis cache.

Redis key format : agent_status:{agent_id}
Redis TTL        : 60 s (PostgreSQL is the source of truth)
"""
import json
import uuid
from datetime import UTC, datetime

import redis.asyncio as aioredis

from crewlayer.db.models import Agent, AgentStatusEnum

_REDIS_PREFIX = "agent_status"
REDIS_TTL = 60  # seconds


def _key(agent_id: uuid.UUID) -> str:
    return f"{_REDIS_PREFIX}:{agent_id}"


def apply_status(
    agent: Agent,
    status: AgentStatusEnum,
    session_id: uuid.UUID | None,
) -> None:
    """Set status fields on an Agent ORM object in-place (no flush/commit)."""
    agent.status = status
    agent.status_updated_at = datetime.now(UTC)
    agent.current_session_id = session_id


async def cache_status(
    agent_id: uuid.UUID,
    status: AgentStatusEnum,
    session_id: uuid.UUID | None,
    updated_at: datetime,
    redis: aioredis.Redis,
) -> None:
    """Write agent status to the Redis cache with TTL."""
    payload = {
        "status": status.value,
        "current_session_id": str(session_id) if session_id else None,
        "updated_at": updated_at.isoformat(),
    }
    await redis.set(_key(agent_id), json.dumps(payload), ex=REDIS_TTL)


async def read_cached_status(
    agent_id: uuid.UUID,
    redis: aioredis.Redis,
) -> dict[str, object] | None:
    """Return the cached status dict, or None on cache miss / parse error."""
    raw = await redis.get(_key(agent_id))
    if raw is None:
        return None
    try:
        result: dict[str, object] = json.loads(raw)
        return result
    except (json.JSONDecodeError, ValueError):
        return None
