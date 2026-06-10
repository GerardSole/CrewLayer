import contextlib
from collections.abc import AsyncGenerator

import pytest_asyncio
import redis.asyncio as aioredis
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from crewlayer.api.middleware import audit as _audit_middleware
from crewlayer.core.config import settings
from crewlayer.core.redis import get_redis
from crewlayer.core.streaming.context_broker import ContextBroker
from crewlayer.db.models import (
    Action,
    Agent,
    AgentRelation,
    ApiKey,
    AuditLog,
    ContextEntry,
    ContextHistory,
    Episode,
    EpisodeMemory,
    Memory,
    Session,
    Tenant,
    WebhookDelivery,
    WebhookEndpoint,
)
from crewlayer.db.session import get_db
from main import app

# Module-level engine shared across all tests in the session.
# NullPool prevents connection reuse across async event-loop boundaries.
_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
_TestSession = async_sessionmaker(_engine, expire_on_commit=False)

# Deletion order respects FK constraints (children before parents)
_CLEANUP_ORDER = [AuditLog, ApiKey, Action, ContextHistory, ContextEntry, EpisodeMemory, Memory, WebhookDelivery, WebhookEndpoint, Session, Episode, AgentRelation, Agent, Tenant]


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

    # Redirect audit background tasks to the NullPool engine so they don't
    # corrupt the pooled app engine between tests (Windows ProactorEventLoop).
    _orig_session_local = _audit_middleware.AsyncSessionLocal
    _audit_middleware.AsyncSessionLocal = _TestSession

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_redis] = _override_get_redis
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        # If the session is in PendingRollbackError state (from a flush exception
        # during the test), roll back first so we can issue new SQL statements.
        with contextlib.suppress(Exception):
            await db.rollback()
        db.expunge_all()
        for model in _CLEANUP_ORDER:
            await db.execute(sa.delete(model))
        await db.commit()
        _audit_middleware.AsyncSessionLocal = _orig_session_local


@pytest_asyncio.fixture
async def context_streaming_client(redis_client: aioredis.Redis) -> AsyncGenerator[AsyncClient, None]:
    """ASGI test client for context subscribe (SSE) tests.

    Uses a *dedicated* Redis connection for the broker (mirroring main.py) so
    that the broker's long-lived pubsub connection doesn't share the same pool
    as the test assertion client.  Each request gets its own DB session to
    allow concurrent SSE + REST calls without asyncpg conflicts.
    """
    # Separate client for the broker — avoids pool contention with redis_client
    broker_redis = aioredis.from_url(settings.REDIS_URL, db=1, decode_responses=True)
    broker = ContextBroker(broker_redis)
    app.state.context_broker = broker

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with _TestSession() as session:
            yield session

    async def _override_get_redis() -> AsyncGenerator[aioredis.Redis, None]:
        yield redis_client

    _orig_session_local = _audit_middleware.AsyncSessionLocal
    _audit_middleware.AsyncSessionLocal = _TestSession

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_redis] = _override_get_redis
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        await broker.aclose()
        with contextlib.suppress(Exception):
            await broker_redis.aclose()
        async with _TestSession() as cleanup_db:
            for model in _CLEANUP_ORDER:
                await cleanup_db.execute(sa.delete(model))
            await cleanup_db.commit()
        _audit_middleware.AsyncSessionLocal = _orig_session_local


@pytest_asyncio.fixture
async def streaming_client(redis_client: aioredis.Redis) -> AsyncGenerator[AsyncClient, None]:
    """ASGI test client for SSE streaming tests.

    Each request gets its own DB session so concurrent SSE + REST calls don't
    share a single asyncpg connection (which can't handle concurrent operations).
    Cleanup is done in a separate session after the test.
    """
    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with _TestSession() as session:
            yield session

    async def _override_get_redis() -> AsyncGenerator[aioredis.Redis, None]:
        yield redis_client

    _orig_session_local = _audit_middleware.AsyncSessionLocal
    _audit_middleware.AsyncSessionLocal = _TestSession

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_redis] = _override_get_redis
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        async with _TestSession() as cleanup_db:
            for model in _CLEANUP_ORDER:
                await cleanup_db.execute(sa.delete(model))
            await cleanup_db.commit()
        _audit_middleware.AsyncSessionLocal = _orig_session_local
