"""Dynamic importance tests: recall boosts importance, decay lowers it, base_importance is immutable."""
import math
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.core.memory.decay import decay_importance
from crewlayer.db.models import Memory

pytestmark = pytest.mark.asyncio

_FAKE_EMBEDDING = [0.1] * 1536


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _setup(client: AsyncClient) -> tuple[dict, dict, dict]:
    r = await client.post("/v1/tenants", json={"name": f"ImpCo-{uuid.uuid4()}"})
    assert r.status_code == 201
    tenant = r.json()
    headers = {"X-API-Key": tenant["initial_api_key"]}
    r = await client.post("/v1/agents", json={"name": "imp-agent"}, headers=headers)
    assert r.status_code == 201
    return tenant, r.json(), headers


async def _seed_memory(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    importance: float = 0.8,
    last_accessed: datetime | None = None,
    created_at: datetime | None = None,
) -> Memory:
    """Insert a Memory row directly, bypassing embedding generation."""
    mem = Memory(
        tenant_id=tenant_id,
        agent_id=agent_id,
        content="test memory content",
        importance=importance,
        base_importance=importance,
        embedding=_FAKE_EMBEDDING,
        tags=[],
        last_accessed=last_accessed,
        created_at=created_at or datetime.now(UTC),
    )
    db.add(mem)
    await db.flush()
    return mem


# ---------------------------------------------------------------------------
# Recall raises importance
# ---------------------------------------------------------------------------

async def test_recall_increments_access_count_and_raises_importance(
    client: AsyncClient, db: AsyncSession
) -> None:
    """After one recall, access_count=1 and importance follows the log formula."""
    tenant, agent, headers = await _setup(client)

    mem = await _seed_memory(db, uuid.UUID(tenant["id"]), uuid.UUID(agent["id"]), importance=0.8)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "crewlayer.core.memory.long.get_embedding",
            AsyncMock(return_value=_FAKE_EMBEDDING),
        )
        r = await client.post(
            f"/v1/agents/{agent['id']}/memory/recall",
            json={"query": "test"},
            headers=headers,
        )

    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) >= 1

    hit = next(x for x in results if x["content"] == "test memory content")
    expected_importance = 0.8 * (1 + math.log(2) * 0.1)
    assert hit["importance"] == pytest.approx(expected_importance, rel=1e-5)
    assert hit["base_importance"] == pytest.approx(0.8, rel=1e-6)

    # ORM object also updated in-session
    assert mem.access_count == 1
    assert mem.importance == pytest.approx(expected_importance, rel=1e-5)


async def test_recall_accumulates_importance_across_multiple_calls(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Three consecutive recalls produce access_count=3 and importance scaled accordingly."""
    tenant, agent, headers = await _setup(client)
    await _seed_memory(db, uuid.UUID(tenant["id"]), uuid.UUID(agent["id"]), importance=0.6)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "crewlayer.core.memory.long.get_embedding",
            AsyncMock(return_value=_FAKE_EMBEDDING),
        )
        for _ in range(3):
            r = await client.post(
                f"/v1/agents/{agent['id']}/memory/recall",
                json={"query": "test"},
                headers=headers,
            )
            assert r.status_code == 200

    hit = r.json()["results"][0]
    # access_count=3 → importance = 0.6 * (1 + log(4) * 0.1)
    expected = 0.6 * (1 + math.log(4) * 0.1)
    assert hit["importance"] == pytest.approx(expected, rel=1e-5)


async def test_recall_updates_last_accessed(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Recall sets last_accessed to approximately now."""
    tenant, agent, headers = await _setup(client)
    before = datetime.now(UTC)
    mem = await _seed_memory(db, uuid.UUID(tenant["id"]), uuid.UUID(agent["id"]))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "crewlayer.core.memory.long.get_embedding",
            AsyncMock(return_value=_FAKE_EMBEDDING),
        )
        await client.post(
            f"/v1/agents/{agent['id']}/memory/recall",
            json={"query": "test"},
            headers=headers,
        )

    after = datetime.now(UTC)
    assert mem.last_accessed is not None
    assert before <= mem.last_accessed <= after


# ---------------------------------------------------------------------------
# base_importance is immutable
# ---------------------------------------------------------------------------

async def test_base_importance_never_changes_on_recall(
    client: AsyncClient, db: AsyncSession
) -> None:
    """base_importance stays at original value across many recalls."""
    tenant, agent, headers = await _setup(client)
    original = 0.75
    mem = await _seed_memory(
        db, uuid.UUID(tenant["id"]), uuid.UUID(agent["id"]), importance=original
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "crewlayer.core.memory.long.get_embedding",
            AsyncMock(return_value=_FAKE_EMBEDDING),
        )
        for _ in range(5):
            await client.post(
                f"/v1/agents/{agent['id']}/memory/recall",
                json={"query": "test"},
                headers=headers,
            )

    assert mem.base_importance == pytest.approx(original, rel=1e-6)
    assert mem.importance > original  # boosted by recalls
    assert mem.access_count == 5


async def test_base_importance_exposed_in_recall_response(
    client: AsyncClient, db: AsyncSession
) -> None:
    """MemoryResponse includes base_importance matching the seeded value."""
    tenant, agent, headers = await _setup(client)
    await _seed_memory(
        db, uuid.UUID(tenant["id"]), uuid.UUID(agent["id"]), importance=0.9
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "crewlayer.core.memory.long.get_embedding",
            AsyncMock(return_value=_FAKE_EMBEDDING),
        )
        r = await client.post(
            f"/v1/agents/{agent['id']}/memory/recall",
            json={"query": "test"},
            headers=headers,
        )

    hit = r.json()["results"][0]
    assert "base_importance" in hit
    assert hit["base_importance"] == pytest.approx(0.9, rel=1e-6)


# ---------------------------------------------------------------------------
# Decay lowers importance
# ---------------------------------------------------------------------------

async def test_decay_reduces_importance_for_stale_memory(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Memory not accessed in > 7 days has importance * 0.95 after one decay run."""
    tenant, agent, headers = await _setup(client)
    old = datetime.now(UTC) - timedelta(days=10)
    mem = await _seed_memory(
        db, uuid.UUID(tenant["id"]), uuid.UUID(agent["id"]),
        importance=0.8, last_accessed=old, created_at=old,
    )

    updated = await decay_importance(db)

    assert updated >= 1
    assert mem.importance == pytest.approx(0.8 * 0.95, rel=1e-6)


async def test_decay_skips_recently_accessed_memory(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Memory accessed within 7 days is not decayed."""
    tenant, agent, headers = await _setup(client)
    recent = datetime.now(UTC) - timedelta(days=3)
    mem = await _seed_memory(
        db, uuid.UUID(tenant["id"]), uuid.UUID(agent["id"]),
        importance=0.8, last_accessed=recent,
    )

    await decay_importance(db)

    assert mem.importance == pytest.approx(0.8, rel=1e-6)


async def test_decay_skips_never_accessed_but_new_memory(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Memory created 3 days ago with no last_accessed is not decayed."""
    tenant, agent, headers = await _setup(client)
    new_mem = await _seed_memory(
        db, uuid.UUID(tenant["id"]), uuid.UUID(agent["id"]),
        importance=0.8, last_accessed=None,
        created_at=datetime.now(UTC) - timedelta(days=3),
    )

    await decay_importance(db)

    assert new_mem.importance == pytest.approx(0.8, rel=1e-6)


async def test_decay_applies_to_never_accessed_old_memory(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Memory created 10 days ago and never accessed uses created_at for the threshold."""
    tenant, agent, headers = await _setup(client)
    old = datetime.now(UTC) - timedelta(days=10)
    mem = await _seed_memory(
        db, uuid.UUID(tenant["id"]), uuid.UUID(agent["id"]),
        importance=0.5, last_accessed=None, created_at=old,
    )

    await decay_importance(db)

    assert mem.importance == pytest.approx(0.5 * 0.95, rel=1e-6)


async def test_decay_floor_prevents_going_below_minimum(
    client: AsyncClient, db: AsyncSession
) -> None:
    """importance is never reduced below 0.01."""
    tenant, agent, headers = await _setup(client)
    old = datetime.now(UTC) - timedelta(days=10)
    # 0.0105 * 0.95 = 0.009975 < 0.01 → should clamp to 0.01
    mem = await _seed_memory(
        db, uuid.UUID(tenant["id"]), uuid.UUID(agent["id"]),
        importance=0.0105, last_accessed=old, created_at=old,
    )

    await decay_importance(db)

    assert mem.importance == pytest.approx(0.01, rel=1e-6)


async def test_decay_skips_memory_already_at_floor(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Memory already at 0.01 is skipped (no-op)."""
    tenant, agent, _ = await _setup(client)
    old = datetime.now(UTC) - timedelta(days=10)
    mem = await _seed_memory(
        db, uuid.UUID(tenant["id"]), uuid.UUID(agent["id"]),
        importance=0.01, last_accessed=old, created_at=old,
    )

    updated = await decay_importance(db)

    # importance == MIN_IMPORTANCE, so no change
    assert updated == 0
    assert mem.importance == pytest.approx(0.01, rel=1e-6)


# ---------------------------------------------------------------------------
# base_importance is immutable under decay
# ---------------------------------------------------------------------------

async def test_base_importance_never_changes_on_decay(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Decay modifies importance but base_importance stays at extraction value."""
    tenant, agent, _ = await _setup(client)
    old = datetime.now(UTC) - timedelta(days=10)
    mem = await _seed_memory(
        db, uuid.UUID(tenant["id"]), uuid.UUID(agent["id"]),
        importance=0.8, last_accessed=old, created_at=old,
    )

    await decay_importance(db)

    assert mem.importance < 0.8
    assert mem.base_importance == pytest.approx(0.8, rel=1e-6)


# ---------------------------------------------------------------------------
# Recall after decay resets from base_importance
# ---------------------------------------------------------------------------

async def test_recall_after_decay_uses_base_importance_not_decayed_value(
    client: AsyncClient, db: AsyncSession
) -> None:
    """After decay lowers importance, a recall recalculates from base_importance."""
    tenant, agent, headers = await _setup(client)
    old = datetime.now(UTC) - timedelta(days=10)
    mem = await _seed_memory(
        db, uuid.UUID(tenant["id"]), uuid.UUID(agent["id"]),
        importance=0.9, last_accessed=old, created_at=old,
    )

    await decay_importance(db)
    decayed_importance = mem.importance
    assert decayed_importance < 0.9

    # Now recall — importance should be recalculated from base_importance=0.9
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "crewlayer.core.memory.long.get_embedding",
            AsyncMock(return_value=_FAKE_EMBEDDING),
        )
        r = await client.post(
            f"/v1/agents/{agent['id']}/memory/recall",
            json={"query": "test"},
            headers=headers,
        )

    hit = r.json()["results"][0]
    # Formula: base_importance=0.9, access_count=1 → 0.9 * (1 + log(2) * 0.1)
    expected = 0.9 * (1 + math.log(2) * 0.1)
    assert hit["importance"] == pytest.approx(expected, rel=1e-5)
    assert hit["base_importance"] == pytest.approx(0.9, rel=1e-6)
    # importance is HIGHER than the decayed value
    assert mem.importance > decayed_importance
