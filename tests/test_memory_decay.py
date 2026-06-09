"""Tests for forget_stale_memories() — all three forgetting rules + endpoints."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.core.memory.decay import forget_stale_memories
from crewlayer.db.models import Memory, MemoryStatusEnum

pytestmark = pytest.mark.asyncio

_FAKE_EMBEDDING = [0.1] * 1536
_NOW = datetime(2030, 6, 1, 3, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _setup(client: AsyncClient) -> tuple[dict, dict, dict]:
    r = await client.post("/v1/tenants", json={"name": f"DecayTenant-{uuid.uuid4()}"})
    assert r.status_code == 201
    tenant = r.json()
    headers = {"X-API-Key": tenant["initial_api_key"]}
    r = await client.post("/v1/agents", json={"name": "decay-agent"}, headers=headers)
    assert r.status_code == 201
    return tenant, r.json(), headers


def _make_memory(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    importance: float = 0.5,
    access_count: int = 0,
    last_accessed: datetime | None = None,
    created_at: datetime | None = None,
    status: MemoryStatusEnum = MemoryStatusEnum.active,
) -> Memory:
    return Memory(
        tenant_id=tenant_id,
        agent_id=agent_id,
        content="decay test content",
        importance=importance,
        base_importance=importance,
        embedding=_FAKE_EMBEDDING,
        tags=[],
        access_count=access_count,
        last_accessed=last_accessed,
        created_at=created_at or (_NOW - timedelta(days=1)),
        status=status,
    )


# ---------------------------------------------------------------------------
# Rule 1: Hard delete
# ---------------------------------------------------------------------------

async def test_hard_delete_stale_low_importance(
    client: AsyncClient, db: AsyncSession
) -> None:
    """importance < 0.05 AND last_accessed > 30 days ago → hard deleted."""
    tenant, agent, _ = await _setup(client)
    tid, aid = uuid.UUID(tenant["id"]), uuid.UUID(agent["id"])

    mem = _make_memory(
        tid, aid,
        importance=0.03,
        last_accessed=_NOW - timedelta(days=35),
    )
    db.add(mem)
    await db.flush()
    mem_id = mem.id

    result = await forget_stale_memories(db, now=_NOW)

    assert result["hard_deleted"] >= 1
    row = (await db.execute(select(Memory).where(Memory.id == mem_id))).scalar_one_or_none()
    assert row is None


async def test_hard_delete_respects_tenant_threshold(
    client: AsyncClient, db: AsyncSession
) -> None:
    """When tenant sets memory_forget_threshold=0.10, memory with importance=0.08 is deleted."""
    r = await client.post("/v1/tenants", json={"name": f"ThreshTenant-{uuid.uuid4()}"})
    assert r.status_code == 201
    tenant = r.json()
    headers = {"X-API-Key": tenant["initial_api_key"]}
    r = await client.post("/v1/agents", json={"name": "t-agent"}, headers=headers)
    assert r.status_code == 201
    agent = r.json()
    tid, aid = uuid.UUID(tenant["id"]), uuid.UUID(agent["id"])

    # Patch tenant settings directly
    from crewlayer.db.models import Tenant
    t_row = (await db.execute(select(Tenant).where(Tenant.id == tid))).scalar_one()
    t_row.settings = {"memory_forget_threshold": 0.10, "memory_delete_after_days": 30}
    await db.flush()

    mem = _make_memory(
        tid, aid,
        importance=0.08,
        last_accessed=_NOW - timedelta(days=35),
    )
    db.add(mem)
    await db.flush()
    mem_id = mem.id

    result = await forget_stale_memories(db, now=_NOW)

    assert result["hard_deleted"] >= 1
    row = (await db.execute(select(Memory).where(Memory.id == mem_id))).scalar_one_or_none()
    assert row is None


async def test_hard_delete_skips_recent_memory(
    client: AsyncClient, db: AsyncSession
) -> None:
    """importance < 0.05 but last_accessed only 5 days ago → NOT deleted."""
    tenant, agent, _ = await _setup(client)
    tid, aid = uuid.UUID(tenant["id"]), uuid.UUID(agent["id"])

    mem = _make_memory(
        tid, aid,
        importance=0.03,
        last_accessed=_NOW - timedelta(days=5),
    )
    db.add(mem)
    await db.flush()
    mem_id = mem.id

    result = await forget_stale_memories(db, now=_NOW)

    assert result["hard_deleted"] == 0
    row = (await db.execute(select(Memory).where(Memory.id == mem_id))).scalar_one_or_none()
    assert row is not None


async def test_hard_delete_skips_disabled_tenant(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Tenant with memory_decay_enabled=False is entirely skipped."""
    r = await client.post("/v1/tenants", json={"name": f"NodecayTenant-{uuid.uuid4()}"})
    assert r.status_code == 201
    tenant = r.json()
    headers = {"X-API-Key": tenant["initial_api_key"]}
    r = await client.post("/v1/agents", json={"name": "nd-agent"}, headers=headers)
    assert r.status_code == 201
    agent = r.json()
    tid, aid = uuid.UUID(tenant["id"]), uuid.UUID(agent["id"])

    from crewlayer.db.models import Tenant
    t_row = (await db.execute(select(Tenant).where(Tenant.id == tid))).scalar_one()
    t_row.settings = {"memory_decay_enabled": False}
    await db.flush()

    mem = _make_memory(
        tid, aid,
        importance=0.01,
        last_accessed=_NOW - timedelta(days=100),
    )
    db.add(mem)
    await db.flush()
    mem_id = mem.id

    result = await forget_stale_memories(db, now=_NOW)

    row = (await db.execute(select(Memory).where(Memory.id == mem_id))).scalar_one_or_none()
    assert row is not None


# ---------------------------------------------------------------------------
# Rule 3: Archive
# ---------------------------------------------------------------------------

async def test_archive_very_stale_medium_importance(
    client: AsyncClient, db: AsyncSession
) -> None:
    """importance < 0.15 AND last_accessed > 60 days ago → archived, not deleted."""
    tenant, agent, _ = await _setup(client)
    tid, aid = uuid.UUID(tenant["id"]), uuid.UUID(agent["id"])

    mem = _make_memory(
        tid, aid,
        importance=0.10,
        last_accessed=_NOW - timedelta(days=65),
    )
    db.add(mem)
    await db.flush()
    mem_id = mem.id

    result = await forget_stale_memories(db, now=_NOW)

    assert result["archived"] >= 1
    assert result["hard_deleted"] == 0
    row = (await db.execute(select(Memory).where(Memory.id == mem_id))).scalar_one_or_none()
    assert row is not None
    assert row.status == MemoryStatusEnum.archived


async def test_archive_respects_tenant_days(
    client: AsyncClient, db: AsyncSession
) -> None:
    """memory_archive_after_days=90 means 65-day-old memory is NOT archived."""
    r = await client.post("/v1/tenants", json={"name": f"ArchTenant-{uuid.uuid4()}"})
    assert r.status_code == 201
    tenant = r.json()
    headers = {"X-API-Key": tenant["initial_api_key"]}
    r = await client.post("/v1/agents", json={"name": "arch-agent"}, headers=headers)
    assert r.status_code == 201
    agent = r.json()
    tid, aid = uuid.UUID(tenant["id"]), uuid.UUID(agent["id"])

    from crewlayer.db.models import Tenant
    t_row = (await db.execute(select(Tenant).where(Tenant.id == tid))).scalar_one()
    t_row.settings = {"memory_archive_after_days": 90}
    await db.flush()

    mem = _make_memory(
        tid, aid,
        importance=0.10,
        last_accessed=_NOW - timedelta(days=65),
    )
    db.add(mem)
    await db.flush()
    mem_id = mem.id

    result = await forget_stale_memories(db, now=_NOW)

    row = (await db.execute(select(Memory).where(Memory.id == mem_id))).scalar_one_or_none()
    assert row is not None
    assert row.status == MemoryStatusEnum.active


# ---------------------------------------------------------------------------
# Rule 2: Unaccessed decay
# ---------------------------------------------------------------------------

async def test_decay_unaccessed_reduces_importance(
    client: AsyncClient, db: AsyncSession
) -> None:
    """access_count=0 AND created > 14 days ago → importance *= 0.80."""
    tenant, agent, _ = await _setup(client)
    tid, aid = uuid.UUID(tenant["id"]), uuid.UUID(agent["id"])

    mem = _make_memory(
        tid, aid,
        importance=0.50,
        access_count=0,
        created_at=_NOW - timedelta(days=20),
    )
    db.add(mem)
    await db.flush()
    mem_id = mem.id

    result = await forget_stale_memories(db, now=_NOW)

    assert result["decayed"] >= 1
    await db.refresh(mem)
    assert mem.importance == pytest.approx(0.50 * 0.80, rel=1e-5)


async def test_decay_skips_accessed_memory(
    client: AsyncClient, db: AsyncSession
) -> None:
    """access_count > 0 → not decayed by Rule 2."""
    tenant, agent, _ = await _setup(client)
    tid, aid = uuid.UUID(tenant["id"]), uuid.UUID(agent["id"])

    mem = _make_memory(
        tid, aid,
        importance=0.50,
        access_count=3,
        created_at=_NOW - timedelta(days=20),
    )
    db.add(mem)
    await db.flush()
    mem_id = mem.id

    result = await forget_stale_memories(db, now=_NOW)

    assert result["decayed"] == 0
    row = (await db.execute(select(Memory).where(Memory.id == mem_id))).scalar_one_or_none()
    assert row is not None
    assert row.importance == pytest.approx(0.50, rel=1e-5)


async def test_decay_skips_newly_created(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Memory created 5 days ago with access_count=0 → not decayed (< 14 day cutoff)."""
    tenant, agent, _ = await _setup(client)
    tid, aid = uuid.UUID(tenant["id"]), uuid.UUID(agent["id"])

    mem = _make_memory(
        tid, aid,
        importance=0.50,
        access_count=0,
        created_at=_NOW - timedelta(days=5),
    )
    db.add(mem)
    await db.flush()
    mem_id = mem.id

    result = await forget_stale_memories(db, now=_NOW)

    assert result["decayed"] == 0
    row = (await db.execute(select(Memory).where(Memory.id == mem_id))).scalar_one_or_none()
    assert row.importance == pytest.approx(0.50, rel=1e-5)


# ---------------------------------------------------------------------------
# Rule priority: delete beats archive
# ---------------------------------------------------------------------------

async def test_rule_priority_delete_over_archive(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Memory matching both Rule 1 and Rule 3 is hard-deleted, not archived."""
    tenant, agent, _ = await _setup(client)
    tid, aid = uuid.UUID(tenant["id"]), uuid.UUID(agent["id"])

    # importance=0.03 < both 0.05 (delete threshold) AND 0.15 (archive threshold)
    # last_accessed 70 days ago > both 30-day delete cutoff AND 60-day archive cutoff
    mem = _make_memory(
        tid, aid,
        importance=0.03,
        last_accessed=_NOW - timedelta(days=70),
    )
    db.add(mem)
    await db.flush()
    mem_id = mem.id

    result = await forget_stale_memories(db, now=_NOW)

    assert result["hard_deleted"] >= 1
    assert result["archived"] == 0
    row = (await db.execute(select(Memory).where(Memory.id == mem_id))).scalar_one_or_none()
    assert row is None


# ---------------------------------------------------------------------------
# Stats endpoint
# ---------------------------------------------------------------------------

async def test_stats_endpoint(client: AsyncClient, db: AsyncSession) -> None:
    """GET /v1/agents/{id}/memories/stats returns correct counts."""
    tenant, agent, headers = await _setup(client)
    tid, aid = uuid.UUID(tenant["id"]), uuid.UUID(agent["id"])

    active = _make_memory(tid, aid, importance=0.8, status=MemoryStatusEnum.active)
    archived = _make_memory(
        tid, aid, importance=0.1, status=MemoryStatusEnum.archived,
        created_at=_NOW - timedelta(days=100),
    )
    db.add(active)
    db.add(archived)
    await db.flush()

    r = await client.get(f"/v1/agents/{agent['id']}/memories/stats", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total_active"] >= 1
    assert body["total_archived"] >= 1
    assert "avg_importance" in body
    assert "oldest_memory" in body
    assert "most_accessed_memory" in body


# ---------------------------------------------------------------------------
# Force-archive endpoint
# ---------------------------------------------------------------------------

async def test_force_archive_endpoint(client: AsyncClient, db: AsyncSession) -> None:
    """POST /v1/agents/{id}/memories/archive archives memories below threshold."""
    tenant, agent, headers = await _setup(client)
    tid, aid = uuid.UUID(tenant["id"]), uuid.UUID(agent["id"])

    low = _make_memory(tid, aid, importance=0.04, status=MemoryStatusEnum.active)
    high = _make_memory(tid, aid, importance=0.80, status=MemoryStatusEnum.active)
    db.add(low)
    db.add(high)
    await db.flush()
    low_id = low.id
    high_id = high.id

    r = await client.post(
        f"/v1/agents/{agent['id']}/memories/archive",
        json={"threshold": 0.10},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["archived_count"] >= 1

    low_row = (await db.execute(select(Memory).where(Memory.id == low_id))).scalar_one()
    high_row = (await db.execute(select(Memory).where(Memory.id == high_id))).scalar_one()
    assert low_row.status == MemoryStatusEnum.archived
    assert high_row.status == MemoryStatusEnum.active


async def test_force_archive_uses_tenant_default_threshold(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Without explicit threshold, uses tenant's memory_forget_threshold (0.05 default)."""
    tenant, agent, headers = await _setup(client)
    tid, aid = uuid.UUID(tenant["id"]), uuid.UUID(agent["id"])

    below = _make_memory(tid, aid, importance=0.03, status=MemoryStatusEnum.active)
    above = _make_memory(tid, aid, importance=0.50, status=MemoryStatusEnum.active)
    db.add(below)
    db.add(above)
    await db.flush()
    below_id = below.id
    above_id = above.id

    r = await client.post(
        f"/v1/agents/{agent['id']}/memories/archive",
        json={},
        headers=headers,
    )
    assert r.status_code == 200

    below_row = (await db.execute(select(Memory).where(Memory.id == below_id))).scalar_one()
    above_row = (await db.execute(select(Memory).where(Memory.id == above_id))).scalar_one()
    assert below_row.status == MemoryStatusEnum.archived
    assert above_row.status == MemoryStatusEnum.active
