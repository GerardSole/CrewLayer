"""Agent export/import portability tests."""
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.db.models import Action, ActionStatus, Memory, MemoryStatusEnum

pytestmark = pytest.mark.asyncio

_EMBED = [1.0] + [0.0] * 1535


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _setup(client: AsyncClient) -> tuple[dict, dict]:
    r = await client.post("/v1/tenants", json={"name": f"PortCo-{uuid.uuid4()}"})
    assert r.status_code == 201
    tenant = r.json()
    return tenant, {"X-API-Key": tenant["initial_api_key"]}


async def _create_agent(client: AsyncClient, headers: dict, **kwargs) -> dict:
    r = await client.post(
        "/v1/agents",
        json={"name": f"ag-{uuid.uuid4()}", **kwargs},
        headers=headers,
    )
    assert r.status_code == 201
    return r.json()


async def _seed_memory(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    content: str = "a memory",
    status: MemoryStatusEnum = MemoryStatusEnum.active,
) -> Memory:
    mem = Memory(
        tenant_id=tenant_id,
        agent_id=agent_id,
        content=content,
        embedding=_EMBED,
        importance=0.7,
        base_importance=0.7,
        access_count=3,
        tags=["tag1"],
        merged_from=[],
        status=status,
    )
    db.add(mem)
    await db.flush()
    return mem


async def _seed_action(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    tool_name: str = "my_tool",
    ts: datetime | None = None,
) -> Action:
    act = Action(
        tenant_id=tenant_id,
        agent_id=agent_id,
        tool_name=tool_name,
        input_params={"q": "hello"},
        output_result={"r": "world"},
        status=ActionStatus.success,
        duration_ms=42,
        metadata_={"extra": "data"},
    )
    db.add(act)
    await db.flush()
    if ts is not None:
        await db.execute(update(Action).where(Action.id == act.id).values(timestamp=ts))
        await db.flush()
    return act


# ---------------------------------------------------------------------------
# Export — structure and content
# ---------------------------------------------------------------------------

async def test_export_returns_attachment(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)

    r = await client.get(f"/v1/agents/{agent['id']}/export", headers=headers)
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "")
    assert r.headers["content-type"].startswith("application/json")


async def test_export_contains_agent_metadata(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(
        client, headers, tags=["foo", "bar"], config={"level": 5}
    )

    r = await client.get(f"/v1/agents/{agent['id']}/export", headers=headers)
    data = r.json()

    assert data["export_version"] == "1.0"
    assert data["source_agent_id"] == agent["id"]
    assert data["agent"]["name"] == agent["name"]
    assert data["agent"]["tags"] == ["foo", "bar"]
    assert data["agent"]["config"] == {"level": 5}
    assert "exported_at" in data


async def test_export_contains_active_and_archived_memories(
    client: AsyncClient, db: AsyncSession
) -> None:
    tenant, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    tid, aid = uuid.UUID(tenant["id"]), uuid.UUID(agent["id"])

    await _seed_memory(db, tid, aid, content="active mem", status=MemoryStatusEnum.active)
    await _seed_memory(db, tid, aid, content="archived mem", status=MemoryStatusEnum.archived)
    await db.commit()

    r = await client.get(f"/v1/agents/{agent['id']}/export", headers=headers)
    data = r.json()
    contents = {m["content"] for m in data["memories"]}
    assert "active mem" in contents
    assert "archived mem" in contents


async def test_export_memory_includes_embedding(
    client: AsyncClient, db: AsyncSession
) -> None:
    tenant, headers = await _setup(client)
    agent = await _create_agent(client, headers)

    await _seed_memory(db, uuid.UUID(tenant["id"]), uuid.UUID(agent["id"]))
    await db.commit()

    r = await client.get(f"/v1/agents/{agent['id']}/export", headers=headers)
    data = r.json()
    assert len(data["memories"]) == 1
    emb = data["memories"][0]["embedding"]
    assert emb is not None and len(emb) == 1536


async def test_export_contains_recent_actions(
    client: AsyncClient, db: AsyncSession
) -> None:
    tenant, headers = await _setup(client)
    agent = await _create_agent(client, headers)

    await _seed_action(db, uuid.UUID(tenant["id"]), uuid.UUID(agent["id"]))
    await db.commit()

    r = await client.get(f"/v1/agents/{agent['id']}/export", headers=headers)
    data = r.json()
    assert len(data["actions"]) == 1
    assert data["actions"][0]["tool_name"] == "my_tool"
    assert data["actions"][0]["metadata"] == {"extra": "data"}


async def test_export_excludes_old_actions(
    client: AsyncClient, db: AsyncSession
) -> None:
    tenant, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    old_ts = datetime.now(UTC) - timedelta(days=91)

    await _seed_action(db, uuid.UUID(tenant["id"]), uuid.UUID(agent["id"]),
                       tool_name="old_tool", ts=old_ts)
    await _seed_action(db, uuid.UUID(tenant["id"]), uuid.UUID(agent["id"]),
                       tool_name="new_tool")
    await db.commit()

    r = await client.get(f"/v1/agents/{agent['id']}/export", headers=headers)
    data = r.json()
    tools = {a["tool_name"] for a in data["actions"]}
    assert "new_tool" in tools
    assert "old_tool" not in tools


async def test_export_contains_closed_sessions_not_active(
    client: AsyncClient
) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)

    # Create and close a session
    sess_r = await client.post(
        "/v1/sessions", json={"agent_id": agent["id"]}, headers=headers
    )
    sess = sess_r.json()
    await client.post(f"/v1/sessions/{sess['id']}/close", headers=headers)

    r = await client.get(f"/v1/agents/{agent['id']}/export", headers=headers)
    data = r.json()
    session_statuses = {s["status"] for s in data["sessions"]}
    assert "closed" in session_statuses
    assert "active" not in session_statuses


async def test_export_contains_episodes(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)

    await client.post(
        f"/v1/agents/{agent['id']}/episodes",
        json={"title": "My Episode"},
        headers=headers,
    )

    r = await client.get(f"/v1/agents/{agent['id']}/export", headers=headers)
    data = r.json()
    assert any(e["title"] == "My Episode" for e in data["episodes"])


async def test_export_unknown_agent_404(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    r = await client.get(f"/v1/agents/{uuid.uuid4()}/export", headers=headers)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Import — creates new agent
# ---------------------------------------------------------------------------

async def test_import_creates_new_agent_with_different_id(
    client: AsyncClient, mocker
) -> None:
    mocker.patch(
        "crewlayer.core.agents.portability.get_embedding",
        new=AsyncMock(return_value=_EMBED),
    )
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers, tags=["x"], config={"n": 1})

    export_r = await client.get(f"/v1/agents/{agent['id']}/export", headers=headers)
    import_r = await client.post("/v1/agents/import", json=export_r.json(), headers=headers)

    assert import_r.status_code == 201
    result = import_r.json()
    assert result["agent"]["id"] != agent["id"]
    assert result["agent"]["name"] == agent["name"]
    assert result["agent"]["tags"] == ["x"]
    assert result["agent"]["config"] == {"n": 1}


async def test_import_preserves_memories(
    client: AsyncClient, db: AsyncSession, mocker
) -> None:
    mocker.patch(
        "crewlayer.core.agents.portability.get_embedding",
        new=AsyncMock(return_value=_EMBED),
    )
    tenant, headers = await _setup(client)
    agent = await _create_agent(client, headers)

    await _seed_memory(db, uuid.UUID(tenant["id"]), uuid.UUID(agent["id"]),
                       content="precious knowledge")
    await db.commit()

    export_r = await client.get(f"/v1/agents/{agent['id']}/export", headers=headers)
    import_r = await client.post("/v1/agents/import", json=export_r.json(), headers=headers)
    assert import_r.status_code == 201

    new_agent_id = uuid.UUID(import_r.json()["agent"]["id"])
    result = await db.execute(
        Memory.__table__.select().where(  # type: ignore[attr-defined]
            (Memory.agent_id == new_agent_id) & (Memory.deleted_at.is_(None))
        )
    )
    rows = result.fetchall()
    contents = {row.content for row in rows}
    assert "precious knowledge" in contents


async def test_import_preserves_actions(
    client: AsyncClient, db: AsyncSession, mocker
) -> None:
    mocker.patch(
        "crewlayer.core.agents.portability.get_embedding",
        new=AsyncMock(return_value=_EMBED),
    )
    tenant, headers = await _setup(client)
    agent = await _create_agent(client, headers)

    await _seed_action(db, uuid.UUID(tenant["id"]), uuid.UUID(agent["id"]),
                       tool_name="important_tool")
    await db.commit()

    export_r = await client.get(f"/v1/agents/{agent['id']}/export", headers=headers)
    import_r = await client.post("/v1/agents/import", json=export_r.json(), headers=headers)
    new_agent_id = uuid.UUID(import_r.json()["agent"]["id"])

    r = await client.get(f"/v1/agents/{new_agent_id}/actions", headers=headers)
    assert r.status_code == 200
    tools = {a["tool_name"] for a in r.json()["items"]}
    assert "important_tool" in tools


async def test_import_returns_id_map(
    client: AsyncClient, db: AsyncSession, mocker
) -> None:
    mocker.patch(
        "crewlayer.core.agents.portability.get_embedding",
        new=AsyncMock(return_value=_EMBED),
    )
    tenant, headers = await _setup(client)
    agent = await _create_agent(client, headers)

    await _seed_memory(db, uuid.UUID(tenant["id"]), uuid.UUID(agent["id"]))
    await _seed_action(db, uuid.UUID(tenant["id"]), uuid.UUID(agent["id"]))
    await db.commit()

    export_r = await client.get(f"/v1/agents/{agent['id']}/export", headers=headers)
    import_r = await client.post("/v1/agents/import", json=export_r.json(), headers=headers)

    result = import_r.json()
    assert "id_map" in result
    assert len(result["id_map"]["memories"]) == 1
    assert len(result["id_map"]["actions"]) == 1
    # Values are the new UUIDs (different from old)
    old_mem_id = export_r.json()["memories"][0]["id"]
    new_mem_id = result["id_map"]["memories"][old_mem_id]
    assert new_mem_id != old_mem_id


async def test_import_preserves_episodes_and_links(
    client: AsyncClient, db: AsyncSession, mocker
) -> None:
    mocker.patch(
        "crewlayer.core.agents.portability.get_embedding",
        new=AsyncMock(return_value=_EMBED),
    )
    tenant, headers = await _setup(client)
    agent = await _create_agent(client, headers)

    await client.post(
        f"/v1/agents/{agent['id']}/episodes",
        json={"title": "Exported Episode"},
        headers=headers,
    )
    export_r = await client.get(f"/v1/agents/{agent['id']}/export", headers=headers)
    import_r = await client.post("/v1/agents/import", json=export_r.json(), headers=headers)
    assert import_r.status_code == 201

    new_agent_id = import_r.json()["agent"]["id"]
    r = await client.get(
        f"/v1/agents/{new_agent_id}/episodes", headers=headers
    )
    assert any(e["title"] == "Exported Episode" for e in r.json())


# ---------------------------------------------------------------------------
# Full roundtrip
# ---------------------------------------------------------------------------

async def test_export_import_roundtrip(
    client: AsyncClient, db: AsyncSession, mocker
) -> None:
    mocker.patch(
        "crewlayer.core.agents.portability.get_embedding",
        new=AsyncMock(return_value=_EMBED),
    )
    tenant, headers = await _setup(client)
    agent = await _create_agent(
        client, headers,
        tags=["alpha", "beta"],
        config={"depth": 2, "mode": "fast"},
    )

    await _seed_memory(db, uuid.UUID(tenant["id"]), uuid.UUID(agent["id"]),
                       content="roundtrip fact")
    await _seed_action(db, uuid.UUID(tenant["id"]), uuid.UUID(agent["id"]),
                       tool_name="rt_tool")
    await db.commit()

    export_r = await client.get(f"/v1/agents/{agent['id']}/export", headers=headers)
    assert export_r.status_code == 200
    export_data = export_r.json()
    assert export_data["export_version"] == "1.0"

    import_r = await client.post("/v1/agents/import", json=export_data, headers=headers)
    assert import_r.status_code == 201

    new = import_r.json()["agent"]
    assert new["tags"] == ["alpha", "beta"]
    assert new["config"] == {"depth": 2, "mode": "fast"}
    assert new["id"] != agent["id"]

    # Verify memory content
    new_agent_id = uuid.UUID(new["id"])
    mem_result = await db.execute(
        Memory.__table__.select().where(  # type: ignore[attr-defined]
            (Memory.agent_id == new_agent_id) & (Memory.deleted_at.is_(None))
        )
    )
    contents = {row.content for row in mem_result.fetchall()}
    assert "roundtrip fact" in contents

    # Verify action
    act_r = await client.get(f"/v1/agents/{new['id']}/actions", headers=headers)
    assert any(a["tool_name"] == "rt_tool" for a in act_r.json()["items"])


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------

async def test_import_invalid_export_version_422(client: AsyncClient) -> None:
    _, headers = await _setup(client)

    r = await client.post(
        "/v1/agents/import",
        json={
            "export_version": "99.0",
            "agent": {"name": "x"},
        },
        headers=headers,
    )
    assert r.status_code == 422


async def test_import_missing_agent_field_422(client: AsyncClient) -> None:
    _, headers = await _setup(client)

    r = await client.post(
        "/v1/agents/import",
        json={"export_version": "1.0"},  # missing "agent"
        headers=headers,
    )
    assert r.status_code == 422


async def test_import_corrupted_memories_skipped_or_fails_cleanly(
    client: AsyncClient, mocker
) -> None:
    """Memories with invalid status should cause a clean 422, not a 500."""
    mocker.patch(
        "crewlayer.core.agents.portability.get_embedding",
        new=AsyncMock(return_value=_EMBED),
    )
    _, headers = await _setup(client)

    bad_payload = {
        "export_version": "1.0",
        "agent": {"name": "bad agent"},
        "memories": [
            {
                "id": str(uuid.uuid4()),
                "content": "test",
                "status": "INVALID_STATUS",
            }
        ],
    }
    r = await client.post("/v1/agents/import", json=bad_payload, headers=headers)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Cross-tenant portability
# ---------------------------------------------------------------------------

async def test_cross_tenant_import(client: AsyncClient, db: AsyncSession, mocker) -> None:
    """Export from tenant A, import into tenant B — full portability."""
    mocker.patch(
        "crewlayer.core.agents.portability.get_embedding",
        new=AsyncMock(return_value=_EMBED),
    )
    tenant_a, headers_a = await _setup(client)
    tenant_b, headers_b = await _setup(client)

    agent_a = await _create_agent(client, headers_a, tags=["cross"])
    await _seed_memory(db, uuid.UUID(tenant_a["id"]), uuid.UUID(agent_a["id"]),
                       content="cross-tenant memory")
    await db.commit()

    export_r = await client.get(f"/v1/agents/{agent_a['id']}/export", headers=headers_a)
    assert export_r.status_code == 200

    import_r = await client.post(
        "/v1/agents/import", json=export_r.json(), headers=headers_b
    )
    assert import_r.status_code == 201
    new = import_r.json()["agent"]
    assert new["id"] != agent_a["id"]
    assert new["tags"] == ["cross"]

    # The new agent belongs to tenant B (can be retrieved with B's key)
    r = await client.get(f"/v1/agents/{new['id']}", headers=headers_b)
    assert r.status_code == 200

    # Cannot be retrieved with A's key
    r2 = await client.get(f"/v1/agents/{new['id']}", headers=headers_a)
    assert r2.status_code == 404
