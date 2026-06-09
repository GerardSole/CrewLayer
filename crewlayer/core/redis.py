from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from redis.asyncio import ConnectionPool, Redis

from crewlayer.core.config import settings

_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(settings.REDIS_URL, decode_responses=True)
    return _pool


async def get_redis() -> AsyncGenerator[Redis, None]:
    """FastAPI dependency that yields a Redis client from the shared connection pool."""
    async with Redis(connection_pool=_get_pool()) as client:
        yield client


RedisDep = Annotated[Redis, Depends(get_redis)]
