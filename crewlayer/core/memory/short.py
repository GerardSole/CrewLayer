import json
from typing import Any, cast

from redis.asyncio import Redis

from crewlayer.core.config import settings


class ShortMemory:
    """Per-session conversation history stored as a Redis list with TTL.

    Key pattern: short:{tenant_id}:{agent_id}:{session_id}
    Messages are prepended (LPUSH) so index 0 is always the most recent.
    The list is capped at MAX_MESSAGES entries and TTL is refreshed on every write.
    """

    MAX_MESSAGES = 200

    def __init__(self, redis: Redis) -> None:
        self._r = redis

    def _key(self, tenant_id: str, agent_id: str, session_id: str) -> str:
        return f"short:{tenant_id}:{agent_id}:{session_id}"

    async def append_message(
        self,
        tenant_id: str,
        agent_id: str,
        session_id: str,
        message: dict[str, Any],
    ) -> None:
        """Prepend a message to the session history and refresh TTL."""
        key = self._key(tenant_id, agent_id, session_id)
        async with self._r.pipeline() as pipe:
            pipe.lpush(key, json.dumps(message))
            pipe.ltrim(key, 0, self.MAX_MESSAGES - 1)
            pipe.expire(key, settings.SHORT_MEMORY_TTL)
            await pipe.execute()

    async def get_messages(
        self,
        tenant_id: str,
        agent_id: str,
        session_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return up to `limit` most recent messages (newest first)."""
        key = self._key(tenant_id, agent_id, session_id)
        raw = cast(list[str], await self._r.lrange(key, 0, limit - 1))
        return [json.loads(r) for r in raw]

    async def clear(self, tenant_id: str, agent_id: str, session_id: str) -> None:
        """Delete the entire session history."""
        key = self._key(tenant_id, agent_id, session_id)
        await self._r.delete(key)
