from collections.abc import AsyncGenerator

import pytest_asyncio
import redis.asyncio as aioredis
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from crewlayer.core.config import settings
from crewlayer.core.redis import get_redis
from crewlayer.db.models import Action, Agent, ApiKey, ContextEntry, Memory, Tenant
from crewlayer.db.session import get_db
from main import app

# Module-level engine shared across all tests in the session.
# NullPool prevents connection reuse across async event-loop boundaries.
_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
_TestSession = async_sessionmaker(_engine, expire_on_commit=False)

# Deletion order respects FK constraints (children before parents)
_CLEANUP_ORDER = [ApiKey, Action, ContextEntry, Memory, Agent, Tenant]


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    async with _TestSession() as session:
        yield session


@pytest_asyncio.fixture
async def redis_client() -> AsyncGenerator[aioredis.Redis, None]:
    """Isolated Redis client on DB 1 (DB 0 is production)."""
    client = aioredis.from_url(settings.REDIS_URL, db=1, decode_responses=True)
    yield client
    await client.flushdb()
    await client.aclose()


@pytest_asyncio.fixture
async def client(db: AsyncSession, redis_client: aioredis.Redis) -> AsyncGenerator[AsyncClient, None]:
    """ASGI test client whose DB and Redis calls share the test's sessions.

    After each test all rows are deleted so tests are fully isolated.
    """
    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db

    async def _override_get_redis() -> AsyncGenerator[aioredis.Redis, None]:
        yield redis_client

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_redis] = _override_get_redis
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        for model in _CLEANUP_ORDER:
            await db.execute(sa.delete(model))
        await db.commit()
