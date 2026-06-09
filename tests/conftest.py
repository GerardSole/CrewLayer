import pytest
import pytest_asyncio
import sqlalchemy as sa
from collections.abc import AsyncGenerator
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from crewlayer.core.config import settings
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
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """ASGI test client whose DB calls share the test's session.

    After each test all rows are deleted so tests are fully isolated.
    """
    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        for model in _CLEANUP_ORDER:
            await db.execute(sa.delete(model))
        await db.commit()
