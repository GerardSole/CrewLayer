"""Real-time agent status tests.

Covers:
- Agents start idle
- Session open → working; session close → idle
- PATCH /agents/{id}/status endpoint
- GET /agents/{id}/status: Redis cache hit and DB fallback
- GET /agents?status= filter
- Redis key is populated after session create and cleared on close
- current_session_id is set and cleared correctly
"""
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.core.agents.status import REDIS_TTL, _key
from crewlayer.db.models import Agent, AgentStatusEnum

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _setup(client: AsyncClient) -> tuple[dict, dict]:
    r = await client.post("/v1/tenants", json={"name": f"StatusCo-{uuid.uuid4()}"})
    assert r.status_code == 201
    tenant = r.json()
    headers = {"X-API-Key": tenant["initial_api_key"]}
    return tenant, headers


async def _create_agent(client: AsyncClient, headers: dict) -> dict:
    r = await client.post("/v1/agents", json={"name": f"agent-{uuid.uuid4()}"}, headers=headers)
    assert r.status_code == 201
    return r.json()


async def _create_session(client: AsyncClient, headers: dict, agent_id: str) -> dict:
    r = await client.post("/v1/sessions", json={"agent_id": agent_id}, headers=headers)
    assert r.status_code == 201
    return r.json()


def _mock_close_deps():
    """Context managers that stub out Claude + embeddings for session close."""
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        return_value=AsyncMock(content=[AsyncMock(text="[]")])
    )
    embed_patch = patch(
        "crewlayer.core.memory.long.get_embedding",
        new_callable=AsyncMock,
        return_value=[1.0] + [0.0] * 1535,
    )
    client_patch = patch("crewlayer.core.memory.extractor._client", mock_client)
    return client_patch, embed_patch


# ---------------------------------------------------------------------------
# Default status
# ---------------------------------------------------------------------------

async def test_new_agent_is_idle(client: AsyncClient) -> None:
    """Newly created agents have status=idle."""
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)

    assert agent["status"] == "idle"
    assert agent["current_session_id"] is None


# ---------------------------------------------------------------------------
# Session lifecycle → idle ↔ working
# ---------------------------------------------------------------------------

async def test_session_open_sets_agent_working(client: AsyncClient, db: AsyncSession) -> None:
    """Creating a session transitions the agent from idle to working."""
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    aid = agent["id"]

    sess = await _create_session(client, headers, aid)

    # Verify via DB
    result = await db.execute(select(Agent).where(Agent.id == uuid.UUID(aid)))
    row = result.scalar_one()
    assert row.status == AgentStatusEnum.working
    assert str(row.current_session_id) == sess["id"]


async def test_session_close_sets_agent_idle(client: AsyncClient, db: AsyncSession) -> None:
    """Closing a session transitions the agent back to idle."""
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    aid = agent["id"]
    sess = await _create_session(client, headers, aid)
    sid = sess["id"]

    client_patch, embed_patch = _mock_close_deps()
    with client_patch, embed_patch:
        r = await client.post(f"/v1/sessions/{sid}/close", headers=headers)
    assert r.status_code == 200

    await db.commit()  # refresh snapshot
    result = await db.execute(select(Agent).where(Agent.id == uuid.UUID(aid)))
    row = result.scalar_one()
    assert row.status == AgentStatusEnum.idle
    assert row.current_session_id is None


async def test_full_cycle_idle_working_idle(client: AsyncClient, db: AsyncSession) -> None:
    """Full cycle: idle → working (on create) → idle (on close)."""
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    aid = agent["id"]

    # Start as idle
    result = await db.execute(select(Agent).where(Agent.id == uuid.UUID(aid)))
    assert result.scalar_one().status == AgentStatusEnum.idle

    # Open session → working
    sess = await _create_session(client, headers, aid)
    await db.commit()
    result = await db.execute(select(Agent).where(Agent.id == uuid.UUID(aid)))
    assert result.scalar_one().status == AgentStatusEnum.working

    # Close session → idle
    client_patch, embed_patch = _mock_close_deps()
    with client_patch, embed_patch:
        await client.post(f"/v1/sessions/{sess['id']}/close", headers=headers)
    await db.commit()
    result = await db.execute(select(Agent).where(Agent.id == uuid.UUID(aid)))
    assert result.scalar_one().status == AgentStatusEnum.idle


# ---------------------------------------------------------------------------
# PATCH /agents/{id}/status
# ---------------------------------------------------------------------------

async def test_patch_status_working(client: AsyncClient, redis_client: object) -> None:
    """PATCH /status with working status succeeds and returns correct body."""
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    aid = agent["id"]

    r = await client.patch(
        f"/v1/agents/{aid}/status",
        json={"status": "working"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "working"
    assert body["agent_id"] == aid
    assert body["current_session_id"] is None


async def test_patch_status_error(client: AsyncClient) -> None:
    """PATCH /status with error status works."""
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)

    r = await client.patch(
        f"/v1/agents/{agent['id']}/status",
        json={"status": "error"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "error"


async def test_patch_status_with_session_id(client: AsyncClient) -> None:
    """PATCH /status can include a session_id."""
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    fake_sid = str(uuid.uuid4())

    r = await client.patch(
        f"/v1/agents/{agent['id']}/status",
        json={"status": "working", "session_id": fake_sid},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "working"
    assert body["current_session_id"] == fake_sid


async def test_patch_status_persists_to_postgresql(
    client: AsyncClient, db: AsyncSession
) -> None:
    """PATCH /status must write through to PostgreSQL, not only the ORM identity map.

    Verification uses db.expunge_all() to clear SQLAlchemy's in-process cache before
    re-querying, so the SELECT is forced to hit the database rather than return the
    locally-mutated object.  This catches the class of bugs where expire_on_commit=False
    + multiple commits per session leave the dirty flag unset and the UPDATE is silently
    skipped.
    """
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    aid = uuid.UUID(agent["id"])

    # ── working ──────────────────────────────────────────────────────────────
    r = await client.patch(
        f"/v1/agents/{aid}/status",
        json={"status": "working"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "working", "PATCH response must reflect new status"

    # Clear identity map → next SELECT must go to the DB
    db.expunge_all()
    result = await db.execute(select(Agent).where(Agent.id == aid))
    row = result.scalar_one()
    assert row.status == AgentStatusEnum.working, (
        f"PostgreSQL has {row.status!r} after PATCH to 'working' — "
        "status update was not committed to the database"
    )

    # GET /v1/agents/{id} must also reflect the change (exercises the REST layer)
    r = await client.get(f"/v1/agents/{aid}", headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "working"

    # ── idle (round-trip back) ────────────────────────────────────────────────
    r = await client.patch(
        f"/v1/agents/{aid}/status",
        json={"status": "idle"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "idle"

    db.expunge_all()
    result = await db.execute(select(Agent).where(Agent.id == aid))
    assert result.scalar_one().status == AgentStatusEnum.idle, (
        "PostgreSQL was not updated when status changed back to 'idle'"
    )

    # ── error ─────────────────────────────────────────────────────────────────
    r = await client.patch(
        f"/v1/agents/{aid}/status",
        json={"status": "error"},
        headers=headers,
    )
    assert r.status_code == 200

    db.expunge_all()
    result = await db.execute(select(Agent).where(Agent.id == aid))
    assert result.scalar_one().status == AgentStatusEnum.error


async def test_patch_status_unknown_agent_returns_404(client: AsyncClient) -> None:
    """PATCH /status on a non-existent agent returns 404."""
    _, headers = await _setup(client)
    r = await client.patch(
        f"/v1/agents/{uuid.uuid4()}/status",
        json={"status": "idle"},
        headers=headers,
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /agents/{id}/status — Redis cache vs DB fallback
# ---------------------------------------------------------------------------

async def test_get_status_returns_current(client: AsyncClient) -> None:
    """GET /status returns the current status from DB when cache is empty."""
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)

    r = await client.get(f"/v1/agents/{agent['id']}/status", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "idle"
    assert body["agent_id"] == agent["id"]


async def test_get_status_serves_from_redis_cache(
    client: AsyncClient,
    redis_client,  # type: ignore[no-untyped-def]
) -> None:
    """GET /status reads from Redis cache when a cache entry exists."""
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    aid = uuid.UUID(agent["id"])

    # Pre-populate the cache with a stale value
    from datetime import UTC, datetime
    stale = {
        "status": "error",
        "current_session_id": None,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    await redis_client.set(_key(aid), json.dumps(stale), ex=REDIS_TTL)

    r = await client.get(f"/v1/agents/{agent['id']}/status", headers=headers)
    assert r.status_code == 200
    # Should return the cached value, not the real DB value
    assert r.json()["status"] == "error"


async def test_get_status_falls_back_to_db_on_cache_miss(
    client: AsyncClient,
    redis_client,  # type: ignore[no-untyped-def]
) -> None:
    """GET /status falls back to DB and warms the cache on cache miss."""
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    aid = uuid.UUID(agent["id"])

    # Ensure no cache entry
    await redis_client.delete(_key(aid))

    r = await client.get(f"/v1/agents/{agent['id']}/status", headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "idle"

    # Cache should now be populated
    cached_raw = await redis_client.get(_key(aid))
    assert cached_raw is not None
    cached = json.loads(cached_raw)
    assert cached["status"] == "idle"


async def test_get_status_unknown_agent_returns_404(client: AsyncClient) -> None:
    """GET /status on a non-existent agent returns 404."""
    _, headers = await _setup(client)
    r = await client.get(f"/v1/agents/{uuid.uuid4()}/status", headers=headers)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /agents?status= filter
# ---------------------------------------------------------------------------

async def test_list_agents_filter_by_status_idle(client: AsyncClient) -> None:
    """GET /agents?status=idle returns only idle agents."""
    _, headers = await _setup(client)
    agent_a = await _create_agent(client, headers)
    agent_b = await _create_agent(client, headers)

    # Set agent_a to error
    await client.patch(
        f"/v1/agents/{agent_a['id']}/status",
        json={"status": "error"},
        headers=headers,
    )

    r = await client.get("/v1/agents?status=idle", headers=headers)
    assert r.status_code == 200
    ids = {a["id"] for a in r.json()}
    assert agent_b["id"] in ids
    assert agent_a["id"] not in ids


async def test_list_agents_filter_by_status_error(client: AsyncClient) -> None:
    """GET /agents?status=error returns only agents in error state."""
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)

    await client.patch(
        f"/v1/agents/{agent['id']}/status",
        json={"status": "error"},
        headers=headers,
    )

    r = await client.get("/v1/agents?status=error", headers=headers)
    assert r.status_code == 200
    assert any(a["id"] == agent["id"] for a in r.json())


async def test_list_agents_no_filter_returns_all(client: AsyncClient) -> None:
    """GET /agents without status filter returns all agents."""
    _, headers = await _setup(client)
    a1 = await _create_agent(client, headers)
    a2 = await _create_agent(client, headers)

    await client.patch(f"/v1/agents/{a1['id']}/status", json={"status": "working"}, headers=headers)

    r = await client.get("/v1/agents", headers=headers)
    ids = {a["id"] for a in r.json()}
    assert a1["id"] in ids
    assert a2["id"] in ids


# ---------------------------------------------------------------------------
# Redis cache is updated on session lifecycle
# ---------------------------------------------------------------------------

async def test_redis_updated_on_session_create(
    client: AsyncClient,
    redis_client,  # type: ignore[no-untyped-def]
) -> None:
    """Creating a session writes working status to Redis."""
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    aid = uuid.UUID(agent["id"])

    sess = await _create_session(client, headers, agent["id"])

    cached_raw = await redis_client.get(_key(aid))
    assert cached_raw is not None
    cached = json.loads(cached_raw)
    assert cached["status"] == "working"
    assert cached["current_session_id"] == sess["id"]


async def test_redis_updated_on_session_close(
    client: AsyncClient,
    redis_client,  # type: ignore[no-untyped-def]
) -> None:
    """Closing a session writes idle status to Redis."""
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    aid = uuid.UUID(agent["id"])
    sess = await _create_session(client, headers, agent["id"])

    client_patch, embed_patch = _mock_close_deps()
    with client_patch, embed_patch:
        await client.post(f"/v1/sessions/{sess['id']}/close", headers=headers)

    cached_raw = await redis_client.get(_key(aid))
    assert cached_raw is not None
    cached = json.loads(cached_raw)
    assert cached["status"] == "idle"
    assert cached["current_session_id"] is None


# ---------------------------------------------------------------------------
# current_session_id in list/get responses
# ---------------------------------------------------------------------------

async def test_current_session_id_in_agent_response(client: AsyncClient) -> None:
    """AgentResponse includes current_session_id after a session is opened."""
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    sess = await _create_session(client, headers, agent["id"])

    r = await client.get(f"/v1/agents/{agent['id']}", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "working"
    assert body["current_session_id"] == sess["id"]


async def test_current_session_id_cleared_after_close(client: AsyncClient) -> None:
    """current_session_id is None after the session is closed."""
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    sess = await _create_session(client, headers, agent["id"])

    client_patch, embed_patch = _mock_close_deps()
    with client_patch, embed_patch:
        await client.post(f"/v1/sessions/{sess['id']}/close", headers=headers)

    r = await client.get(f"/v1/agents/{agent['id']}", headers=headers)
    body = r.json()
    assert body["status"] == "idle"
    assert body["current_session_id"] is None
