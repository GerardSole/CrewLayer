"""Duplicate detection and merge tests for long-term memory."""
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.core.memory.long import LongMemory
from crewlayer.db.models import Memory

pytestmark = pytest.mark.asyncio

# Unit vector along dim-0: all others zero
_FAKE_EMBED_A = [1.0] + [0.0] * 1535
# Unit vector along dim-1: orthogonal to A (cosine sim = 0)
_FAKE_EMBED_C = [0.0, 1.0] + [0.0] * 1534
# Same direction as A (cosine sim = 1)
_FAKE_EMBED_B = [2.0] + [0.0] * 1535
_MERGED_EMBED = [1.5] + [0.0] * 1535


async def _setup(client: AsyncClient) -> tuple[dict, dict, dict]:
    r = await client.post("/v1/tenants", json={"name": f"DedupCo-{uuid.uuid4()}"})
    assert r.status_code == 201
    tenant = r.json()
    headers = {"X-API-Key": tenant["initial_api_key"]}
    r = await client.post("/v1/agents", json={"name": "dedup-agent"}, headers=headers)
    assert r.status_code == 201
    return tenant, r.json(), headers


async def _seed_memory(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    content: str = "original memory content",
    embedding: list[float] | None = None,
    importance: float = 0.5,
    access_count: int = 0,
    merged_from: list[uuid.UUID] | None = None,
    deleted_at: datetime | None = None,
    created_at: datetime | None = None,
) -> Memory:
    kwargs: dict = dict(
        tenant_id=tenant_id,
        agent_id=agent_id,
        content=content,
        embedding=embedding or _FAKE_EMBED_A,
        importance=importance,
        base_importance=importance,
        access_count=access_count,
        tags=[],
        merged_from=merged_from or [],
        deleted_at=deleted_at,
    )
    if created_at is not None:
        kwargs["created_at"] = created_at
    mem = Memory(**kwargs)
    db.add(mem)
    await db.flush()
    return mem


# ---------------------------------------------------------------------------
# Similar memories are merged
# ---------------------------------------------------------------------------

async def test_similar_memories_are_merged(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Two memories with cosine sim > 0.90 produce a single merged memory."""
    tenant, agent, headers = await _setup(client)
    tid = uuid.UUID(tenant["id"])
    aid = uuid.UUID(agent["id"])

    original = await _seed_memory(db, tid, aid, content="The user prefers dark mode.")

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="The user prefers dark mode and large fonts.")]

    with (
        patch("crewlayer.core.memory.long.get_embedding", AsyncMock(return_value=_FAKE_EMBED_A)),
        patch("crewlayer.core.memory.merger.get_embedding", AsyncMock(return_value=_MERGED_EMBED), create=True),
        patch(
            "crewlayer.core.memory.merger._client",
            new_callable=lambda: type(
                "MockClient", (), {
                    "messages": type("Msgs", (), {
                        "create": AsyncMock(return_value=mock_response)
                    })()
                }
            ),
        ),
    ):
        lm = LongMemory(db)
        merged = await lm.save(tid, aid, "The user likes dark mode and big text.", importance=0.6)

    # Original should be soft-deleted
    await db.refresh(original)
    assert original.deleted_at is not None

    # Merged memory has merged_from pointing to original
    assert original.id in merged.merged_from
    assert merged.id != original.id

    # Only one live memory in DB
    live = (
        await db.execute(
            select(Memory).where(
                Memory.agent_id == aid,
                Memory.tenant_id == tid,
                Memory.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    assert len(live) == 1
    assert live[0].id == merged.id


async def test_merge_keeps_higher_base_importance(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Merged memory inherits the higher base_importance of the two originals."""
    tenant, agent, _ = await _setup(client)
    tid, aid = uuid.UUID(tenant["id"]), uuid.UUID(agent["id"])

    await _seed_memory(db, tid, aid, importance=0.8)

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="merged")]

    with (
        patch("crewlayer.core.memory.long.get_embedding", AsyncMock(return_value=_FAKE_EMBED_A)),
        patch(
            "crewlayer.core.memory.merger._client",
            new_callable=lambda: type(
                "MockClient", (), {
                    "messages": type("Msgs", (), {
                        "create": AsyncMock(return_value=mock_response)
                    })()
                }
            ),
        ),
    ):
        lm = LongMemory(db)
        # incoming has lower importance (0.5) → merged should keep 0.8
        merged = await lm.save(tid, aid, "similar content", importance=0.5)

    assert merged.base_importance == pytest.approx(0.8)
    assert merged.importance == pytest.approx(0.8)


async def test_merge_keeps_higher_importance_when_incoming_is_higher(
    client: AsyncClient, db: AsyncSession
) -> None:
    """When incoming importance > existing, merged gets incoming value."""
    tenant, agent, _ = await _setup(client)
    tid, aid = uuid.UUID(tenant["id"]), uuid.UUID(agent["id"])

    await _seed_memory(db, tid, aid, importance=0.4)

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="merged")]

    with (
        patch("crewlayer.core.memory.long.get_embedding", AsyncMock(return_value=_FAKE_EMBED_A)),
        patch(
            "crewlayer.core.memory.merger._client",
            new_callable=lambda: type(
                "MockClient", (), {
                    "messages": type("Msgs", (), {
                        "create": AsyncMock(return_value=mock_response)
                    })()
                }
            ),
        ),
    ):
        lm = LongMemory(db)
        merged = await lm.save(tid, aid, "similar content", importance=0.9)

    assert merged.base_importance == pytest.approx(0.9)


async def test_merge_sums_access_count(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Merged memory inherits the existing memory's access_count."""
    tenant, agent, _ = await _setup(client)
    tid, aid = uuid.UUID(tenant["id"]), uuid.UUID(agent["id"])

    await _seed_memory(db, tid, aid, access_count=7)

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="merged")]

    with (
        patch("crewlayer.core.memory.long.get_embedding", AsyncMock(return_value=_FAKE_EMBED_A)),
        patch(
            "crewlayer.core.memory.merger._client",
            new_callable=lambda: type(
                "MockClient", (), {
                    "messages": type("Msgs", (), {
                        "create": AsyncMock(return_value=mock_response)
                    })()
                }
            ),
        ),
    ):
        lm = LongMemory(db)
        merged = await lm.save(tid, aid, "similar content")

    assert merged.access_count == 7


# ---------------------------------------------------------------------------
# Distinct memories are NOT merged
# ---------------------------------------------------------------------------

async def test_distinct_memories_not_merged(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Two memories below the similarity threshold are saved independently."""
    tenant, agent, _ = await _setup(client)
    tid, aid = uuid.UUID(tenant["id"]), uuid.UUID(agent["id"])

    original = await _seed_memory(db, tid, aid, embedding=_FAKE_EMBED_A)

    # Return a distant embedding for the second save so similarity < 0.90
    embed_sequence = iter([_FAKE_EMBED_C, _FAKE_EMBED_C])

    with patch(
        "crewlayer.core.memory.long.get_embedding",
        AsyncMock(side_effect=embed_sequence),
    ):
        lm = LongMemory(db)
        new_mem = await lm.save(tid, aid, "completely different topic")

    # Original must NOT be soft-deleted
    await db.refresh(original)
    assert original.deleted_at is None

    # New memory has no merged_from
    assert new_mem.merged_from == []
    assert new_mem.id != original.id

    live = (
        await db.execute(
            select(Memory).where(
                Memory.agent_id == aid,
                Memory.tenant_id == tid,
                Memory.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    assert len(live) == 2


async def test_merged_from_empty_for_normal_save(
    client: AsyncClient, db: AsyncSession
) -> None:
    """First save into an empty agent has merged_from=[]."""
    tenant, agent, _ = await _setup(client)
    tid, aid = uuid.UUID(tenant["id"]), uuid.UUID(agent["id"])

    with patch("crewlayer.core.memory.long.get_embedding", AsyncMock(return_value=_FAKE_EMBED_A)):
        lm = LongMemory(db)
        mem = await lm.save(tid, aid, "brand new memory")

    assert mem.merged_from == []


# ---------------------------------------------------------------------------
# merged_from populated correctly in API response
# ---------------------------------------------------------------------------

async def test_merged_from_in_recall_response(
    client: AsyncClient, db: AsyncSession
) -> None:
    """After a merge, recall response includes merged_from with the original ID."""
    tenant, agent, headers = await _setup(client)
    tid, aid = uuid.UUID(tenant["id"]), uuid.UUID(agent["id"])

    original = await _seed_memory(db, tid, aid, content="User likes Python.")

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="User likes Python and type hints.")]

    with (
        patch("crewlayer.core.memory.long.get_embedding", AsyncMock(return_value=_FAKE_EMBED_A)),
        patch(
            "crewlayer.core.memory.merger._client",
            new_callable=lambda: type(
                "MockClient", (), {
                    "messages": type("Msgs", (), {
                        "create": AsyncMock(return_value=mock_response)
                    })()
                }
            ),
        ),
    ):
        lm = LongMemory(db)
        await lm.save(tid, aid, "User loves Python and type annotations.", importance=0.6)

    # Now recall — patch embedding again
    with patch("crewlayer.core.memory.long.get_embedding", AsyncMock(return_value=_FAKE_EMBED_A)):
        r = await client.post(
            f"/v1/agents/{agent['id']}/memory/recall",
            json={"query": "Python"},
            headers=headers,
        )

    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) == 1
    assert str(original.id) in results[0]["merged_from"]


async def test_merged_from_in_list_response(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET /memory includes merged_from in each item."""
    tenant, agent, headers = await _setup(client)
    tid, aid = uuid.UUID(tenant["id"]), uuid.UUID(agent["id"])

    original = await _seed_memory(db, tid, aid)

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="merged memory")]

    with (
        patch("crewlayer.core.memory.long.get_embedding", AsyncMock(return_value=_FAKE_EMBED_A)),
        patch(
            "crewlayer.core.memory.merger._client",
            new_callable=lambda: type(
                "MockClient", (), {
                    "messages": type("Msgs", (), {
                        "create": AsyncMock(return_value=mock_response)
                    })()
                }
            ),
        ),
    ):
        lm = LongMemory(db)
        await lm.save(tid, aid, "very similar content")

    r = await client.get(f"/v1/agents/{agent['id']}/memory", headers=headers)
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert str(original.id) in items[0]["merged_from"]


# ---------------------------------------------------------------------------
# History endpoint
# ---------------------------------------------------------------------------

async def test_history_endpoint_returns_lineage(
    client: AsyncClient, db: AsyncSession
) -> None:
    """History endpoint returns ancestor chain sorted oldest-to-newest."""
    tenant, agent, headers = await _setup(client)
    tid, aid = uuid.UUID(tenant["id"]), uuid.UUID(agent["id"])

    ancestor = await _seed_memory(
        db, tid, aid,
        content="ancestor",
        deleted_at=datetime.now(UTC),
    )
    merged = await _seed_memory(
        db, tid, aid,
        content="merged result",
        merged_from=[ancestor.id],
    )

    r = await client.get(
        f"/v1/agents/{agent['id']}/memories/{merged.id}/history",
        headers=headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["memory_id"] == str(merged.id)
    lineage = data["lineage"]
    assert len(lineage) == 2
    # Oldest first
    assert lineage[0]["id"] == str(ancestor.id)
    assert lineage[1]["id"] == str(merged.id)


async def test_history_endpoint_no_ancestors(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Memory with no merged_from returns lineage with just itself."""
    tenant, agent, headers = await _setup(client)
    tid, aid = uuid.UUID(tenant["id"]), uuid.UUID(agent["id"])

    mem = await _seed_memory(db, tid, aid)

    r = await client.get(
        f"/v1/agents/{agent['id']}/memories/{mem.id}/history",
        headers=headers,
    )
    assert r.status_code == 200
    lineage = r.json()["lineage"]
    assert len(lineage) == 1
    assert lineage[0]["id"] == str(mem.id)


async def test_history_endpoint_404_unknown_memory(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Unknown memory_id returns 404."""
    tenant, agent, headers = await _setup(client)

    r = await client.get(
        f"/v1/agents/{agent['id']}/memories/{uuid.uuid4()}/history",
        headers=headers,
    )
    assert r.status_code == 404


async def test_history_endpoint_deep_lineage(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Multi-generation chain: A merged into B, B merged into C → history is [A, B, C]."""
    from datetime import timedelta
    tenant, agent, headers = await _setup(client)
    tid, aid = uuid.UUID(tenant["id"]), uuid.UUID(agent["id"])

    now = datetime.now(UTC)
    mem_a = await _seed_memory(
        db, tid, aid, content="A",
        deleted_at=now - timedelta(seconds=20),
        created_at=now - timedelta(seconds=20),
    )
    mem_b = await _seed_memory(
        db, tid, aid,
        content="B",
        merged_from=[mem_a.id],
        deleted_at=now - timedelta(seconds=10),
        created_at=now - timedelta(seconds=10),
    )
    mem_c = await _seed_memory(db, tid, aid, content="C", merged_from=[mem_b.id], created_at=now)

    r = await client.get(
        f"/v1/agents/{agent['id']}/memories/{mem_c.id}/history",
        headers=headers,
    )
    assert r.status_code == 200
    ids = [e["id"] for e in r.json()["lineage"]]
    assert ids == [str(mem_a.id), str(mem_b.id), str(mem_c.id)]
