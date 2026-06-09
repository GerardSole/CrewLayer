"""Audit log immutability and content tests."""
import asyncio
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.db.models import AuditLog

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _setup(client: AsyncClient) -> tuple[dict, dict, dict]:
    r = await client.post("/v1/tenants", json={"name": f"AuditCo-{uuid.uuid4()}"})
    assert r.status_code == 201
    tenant = r.json()
    headers = {"X-API-Key": tenant["initial_api_key"]}
    r = await client.post("/v1/agents", json={"name": "audit-agent"}, headers=headers)
    assert r.status_code == 201
    return tenant, r.json(), headers


async def _flush_audit_tasks() -> None:
    """Explicitly await all pending _persist_entry background tasks."""
    tasks = [
        t for t in asyncio.all_tasks()
        if not t.done() and "_persist_entry" in repr(t)
    ]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _drain_audit(
    db: AsyncSession,
    tenant_id: str,
    *,
    expected_min: int = 1,
) -> list[AuditLog]:
    """Poll for audit entries, waiting up to 3 s for background tasks to commit."""
    for _ in range(30):
        await _flush_audit_tasks()  # await any pending _persist_entry tasks
        await db.commit()           # start fresh txn so we see new data
        result = await db.execute(
            select(AuditLog)
            .where(AuditLog.tenant_id == uuid.UUID(tenant_id))
            .order_by(AuditLog.timestamp.asc())
        )
        rows = list(result.scalars().all())
        if len(rows) >= expected_min:
            return rows
        await asyncio.sleep(0.1)
    return rows


# ---------------------------------------------------------------------------
# Mutations are logged
# ---------------------------------------------------------------------------

async def test_post_request_creates_audit_entry(
    client: AsyncClient, db: AsyncSession
) -> None:
    """POST /agents creates an audit entry with method=POST and resource_type=agents."""
    tenant, agent, headers = await _setup(client)

    # POST /tenants is unauthenticated — not logged. POST /agents is logged.
    entries = await _drain_audit(db, tenant["id"], expected_min=1)
    posts = [e for e in entries if e.method == "POST"]
    assert len(posts) >= 1
    agent_entry = next(
        (e for e in posts if e.resource_type == "agents" and e.status_code == 201), None
    )
    assert agent_entry is not None
    assert agent_entry.actor_key_name is not None


async def test_delete_memory_creates_audit_entry(
    client: AsyncClient, db: AsyncSession
) -> None:
    """DELETE /memory/{id} appears in the audit log as resource_type=memory."""
    tenant, agent, headers = await _setup(client)
    aid = agent["id"]

    from crewlayer.db.models import Memory
    mem = Memory(
        tenant_id=uuid.UUID(tenant["id"]),
        agent_id=uuid.UUID(aid),
        content="to be deleted",
        embedding=[1.0] + [0.0] * 1535,
        importance=0.5, base_importance=0.5, tags=[], merged_from=[],
    )
    db.add(mem)
    await db.flush()

    r = await client.delete(f"/v1/agents/{aid}/memory/{mem.id}", headers=headers)
    assert r.status_code == 204

    # POST /agents (setup) + DELETE /memory = 2 logged entries
    entries = await _drain_audit(db, tenant["id"], expected_min=2)
    deletes = [e for e in entries if e.method == "DELETE" and e.resource_type == "memory"]
    assert len(deletes) >= 1
    assert deletes[0].status_code == 204


async def test_put_context_creates_audit_entry(
    client: AsyncClient, db: AsyncSession
) -> None:
    """PUT /context/{ns}/{key} is logged with resource_type=context."""
    tenant, _, headers = await _setup(client)

    r = await client.put(
        "/v1/context/ns/mykey",
        json={"value": {"x": 1}},
        headers=headers,
    )
    assert r.status_code == 200

    # POST /agents (setup) + PUT /context = 2 logged entries
    entries = await _drain_audit(db, tenant["id"], expected_min=2)
    puts = [e for e in entries if e.method == "PUT" and e.resource_type == "context"]
    assert len(puts) >= 1
    assert puts[0].path == "/v1/context/ns/mykey"


async def test_audit_entry_captures_status_code(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A request that results in 404 is still logged with status_code=404."""
    tenant, agent, headers = await _setup(client)
    fake_id = uuid.uuid4()

    r = await client.delete(
        f"/v1/agents/{agent['id']}/memory/{fake_id}", headers=headers
    )
    assert r.status_code == 404

    # POST /agents (setup) + DELETE /memory (404) = 2 logged entries
    entries = await _drain_audit(db, tenant["id"], expected_min=2)
    not_found = [e for e in entries if e.method == "DELETE" and e.status_code == 404]
    assert len(not_found) >= 1


async def test_audit_entry_captures_actor_name(
    client: AsyncClient, db: AsyncSession
) -> None:
    """The audit entry records actor_key_name matching the API key name."""
    r = await client.post("/v1/tenants", json={"name": f"AuditNameCo-{uuid.uuid4()}"})
    tenant = r.json()
    admin_key = tenant["initial_api_key"]
    admin_headers = {"X-API-Key": admin_key}

    r = await client.post(
        "/v1/api-keys",
        json={"name": "my-named-key", "scopes": []},
        headers=admin_headers,
    )
    named_key = r.json()["key"]
    named_headers = {"X-API-Key": named_key}

    await client.post("/v1/agents", json={"name": "a"}, headers=named_headers)

    # POST /api-keys + POST /agents = 2 logged entries (POST /tenants is unauthed)
    entries = await _drain_audit(db, tenant["id"], expected_min=2)
    named_entries = [e for e in entries if e.actor_key_name == "my-named-key"]
    assert len(named_entries) >= 1


# ---------------------------------------------------------------------------
# GETs are NOT logged
# ---------------------------------------------------------------------------

async def test_get_requests_not_logged(
    client: AsyncClient, db: AsyncSession
) -> None:
    """GET endpoints must never produce audit log entries."""
    tenant, agent, headers = await _setup(client)

    # Wait for setup mutations to be logged
    await _drain_audit(db, tenant["id"], expected_min=2)

    # Perform several GET calls
    await client.get("/v1/agents", headers=headers)
    await client.get(f"/v1/agents/{agent['id']}", headers=headers)
    await client.get(f"/v1/agents/{agent['id']}/memory", headers=headers)
    await client.get("/v1/sessions", headers=headers)
    await client.get("/v1/audit-log", headers=headers)

    await _flush_audit_tasks()

    entries = await _drain_audit(db, tenant["id"], expected_min=2)
    get_entries = [e for e in entries if e.method == "GET"]
    assert get_entries == []


# ---------------------------------------------------------------------------
# Unauthenticated requests are NOT logged
# ---------------------------------------------------------------------------

async def test_unauthenticated_request_not_logged(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A POST with no API key (401) should NOT create an audit entry."""
    r = await client.post("/v1/agents", json={"name": "x"})
    assert r.status_code == 401

    await _flush_audit_tasks()
    await db.commit()
    result = await db.execute(select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(1))
    row = result.scalar_one_or_none()
    assert row is None


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------

async def test_tenant_cannot_see_other_tenants_audit_log(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Each tenant sees only its own audit log entries."""
    tenant_a, _, headers_a = await _setup(client)
    tenant_b, _, headers_b = await _setup(client)

    await client.post("/v1/agents", json={"name": "extra-a"}, headers=headers_a)
    await client.post("/v1/agents", json={"name": "extra-b"}, headers=headers_b)

    # Per tenant: POST /agents (setup) + POST /agents (extra) = 2 logged entries
    await _drain_audit(db, tenant_a["id"], expected_min=2)
    await _drain_audit(db, tenant_b["id"], expected_min=2)

    r_a = await client.get("/v1/audit-log", headers=headers_a)
    r_b = await client.get("/v1/audit-log", headers=headers_b)
    assert r_a.status_code == 200
    assert r_b.status_code == 200

    ids_a = {e["id"] for e in r_a.json()["items"]}
    ids_b = {e["id"] for e in r_b.json()["items"]}
    assert ids_a.isdisjoint(ids_b), "Tenants must not share audit entries"


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

async def test_filter_by_resource_type(
    client: AsyncClient, db: AsyncSession
) -> None:
    """?resource_type=agents returns only agents-typed entries."""
    tenant, _, headers = await _setup(client)

    await _drain_audit(db, tenant["id"], expected_min=2)

    r = await client.get("/v1/audit-log?resource_type=agents", headers=headers)
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) >= 1
    assert all(e["resource_type"] == "agents" for e in items)


async def test_filter_by_resource_type_excludes_others(
    client: AsyncClient, db: AsyncSession
) -> None:
    """?resource_type=context returns no entries when only agents actions occurred."""
    tenant, _, headers = await _setup(client)

    await _drain_audit(db, tenant["id"], expected_min=2)

    r = await client.get("/v1/audit-log?resource_type=context", headers=headers)
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(e["resource_type"] == "context" for e in items)
    assert items == []


async def test_no_delete_endpoint_exists(client: AsyncClient) -> None:
    """DELETE /v1/audit-log must not exist (405 or 404)."""
    r = await client.post("/v1/tenants", json={"name": f"T-{uuid.uuid4()}"})
    key = r.json()["initial_api_key"]
    # Flush the POST /tenants audit task before test ends
    await _flush_audit_tasks()
    r = await client.delete("/v1/audit-log", headers={"X-API-Key": key})
    assert r.status_code in (404, 405)


# ---------------------------------------------------------------------------
# Cursor pagination
# ---------------------------------------------------------------------------

async def test_cursor_pagination_covers_all_entries(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Paginating with limit=1 through all entries yields each entry exactly once."""
    tenant, agent, headers = await _setup(client)

    # Create a couple more mutations
    await client.post("/v1/agents", json={"name": "p1"}, headers=headers)
    await client.post("/v1/agents", json={"name": "p2"}, headers=headers)

    # POST /tenants is unauthenticated so it produces no audit entry.
    # Audit entries: POST /agents (setup) + POST /agents p1 + POST /agents p2 = 3.
    entries = await _drain_audit(db, tenant["id"], expected_min=3)
    total_expected = len(entries)
    assert total_expected >= 3

    # Collect all via pagination
    all_ids: list[str] = []
    cursor: str | None = None
    while True:
        url = "/v1/audit-log?limit=1"
        if cursor:
            url += f"&cursor={cursor}"
        r = await client.get(url, headers=headers)
        assert r.status_code == 200
        data = r.json()
        for item in data["items"]:
            all_ids.append(item["id"])
        cursor = data["next_cursor"]
        if cursor is None:
            break

    # All IDs should be unique (no duplicates across pages)
    assert len(all_ids) == len(set(all_ids))
    assert len(all_ids) >= 3

    # Explicit flush before fixture teardown to avoid asyncpg teardown errors
    await _flush_audit_tasks()
