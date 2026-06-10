"""Immutable context history: write/delete creates history, rollback restores, tenant isolation."""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.db.models import ContextHistory, ContextOperationEnum

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _setup(client: AsyncClient) -> tuple[dict, dict]:
    r = await client.post("/v1/tenants", json={"name": f"HisCo-{uuid.uuid4()}"})
    assert r.status_code == 201
    tenant = r.json()
    headers = {"X-API-Key": tenant["initial_api_key"]}
    return tenant, headers


async def _put(client: AsyncClient, headers: dict, ns: str, key: str, value: dict, **extra):
    return await client.put(
        f"/v1/context/{ns}/{key}",
        json={"value": value, **extra},
        headers=headers,
    )


async def _delete(client: AsyncClient, headers: dict, ns: str, key: str):
    return await client.delete(f"/v1/context/{ns}/{key}", headers=headers)


async def _history(client: AsyncClient, headers: dict, ns: str, key: str, **params):
    return await client.get(f"/v1/context/{ns}/{key}/history", headers=headers, params=params)


async def _at_version(client: AsyncClient, headers: dict, ns: str, key: str, version: int):
    return await client.get(f"/v1/context/{ns}/{key}/history/{version}", headers=headers)


async def _rollback(client: AsyncClient, headers: dict, ns: str, key: str, target_version: int):
    return await client.post(
        f"/v1/context/{ns}/{key}/rollback",
        json={"target_version": target_version},
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Write generates history entry
# ---------------------------------------------------------------------------

async def test_write_creates_history_entry(client: AsyncClient, db: AsyncSession) -> None:
    """First PUT → history entry with operation=created and version=1."""
    _, headers = await _setup(client)

    r = await _put(client, headers, "ns", "mykey", {"x": 1})
    assert r.status_code == 200

    r2 = await _history(client, headers, "ns", "mykey")
    assert r2.status_code == 200
    entries = r2.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["version"] == 1
    assert entries[0]["operation"] == "created"
    assert entries[0]["value"] == {"x": 1}


async def test_second_write_appends_updated_entry(client: AsyncClient) -> None:
    """Second PUT → new history entry with operation=updated and incremented version."""
    _, headers = await _setup(client)

    await _put(client, headers, "ns", "k", {"a": 1})
    await _put(client, headers, "ns", "k", {"a": 2})

    r = await _history(client, headers, "ns", "k")
    entries = r.json()["entries"]
    # Ordered newest-first
    assert entries[0]["version"] == 2
    assert entries[0]["operation"] == "updated"
    assert entries[0]["value"] == {"a": 2}
    assert entries[1]["version"] == 1
    assert entries[1]["operation"] == "created"


async def test_three_writes_three_history_entries(client: AsyncClient) -> None:
    """Each write produces exactly one history entry."""
    _, headers = await _setup(client)

    for i in range(3):
        await _put(client, headers, "ns", "seq", {"i": i})

    r = await _history(client, headers, "ns", "seq")
    assert len(r.json()["entries"]) == 3


# ---------------------------------------------------------------------------
# Delete generates history entry
# ---------------------------------------------------------------------------

async def test_delete_creates_deleted_history_entry(client: AsyncClient) -> None:
    """DELETE → history entry with operation=deleted and value=null."""
    _, headers = await _setup(client)

    await _put(client, headers, "ns", "gone", {"keep": False})
    r = await _delete(client, headers, "ns", "gone")
    assert r.status_code == 204

    r2 = await _history(client, headers, "ns", "gone")
    entries = r2.json()["entries"]
    assert entries[0]["operation"] == "deleted"
    assert entries[0]["value"] is None
    assert entries[0]["version"] == 2  # 1 (created) + 1 (deleted)


async def test_write_delete_write_has_three_entries(client: AsyncClient) -> None:
    """Write → delete → write produces 3 history entries across separate versions."""
    _, headers = await _setup(client)

    await _put(client, headers, "ns", "wdw", {"step": 1})
    await _delete(client, headers, "ns", "wdw")
    await _put(client, headers, "ns", "wdw", {"step": 3})

    r = await _history(client, headers, "ns", "wdw")
    entries = r.json()["entries"]
    assert len(entries) == 3
    ops = [e["operation"] for e in reversed(entries)]  # oldest first
    assert ops == ["created", "deleted", "created"]


# ---------------------------------------------------------------------------
# GET /history/{version}
# ---------------------------------------------------------------------------

async def test_at_version_returns_correct_value(client: AsyncClient) -> None:
    """GET /history/1 returns the value written at version 1."""
    _, headers = await _setup(client)

    await _put(client, headers, "ns", "pt", {"v": "first"})
    await _put(client, headers, "ns", "pt", {"v": "second"})

    r = await _at_version(client, headers, "ns", "pt", 1)
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 1
    assert body["value"] == {"v": "first"}
    assert body["operation"] == "created"


async def test_at_version_returns_404_for_nonexistent(client: AsyncClient) -> None:
    """Version that does not exist returns 404."""
    _, headers = await _setup(client)

    await _put(client, headers, "ns", "onlyone", {"x": 1})

    r = await _at_version(client, headers, "ns", "onlyone", 999)
    assert r.status_code == 404


async def test_at_version_deleted_entry_has_null_value(client: AsyncClient) -> None:
    """The history entry for a deleted version has value=null."""
    _, headers = await _setup(client)

    await _put(client, headers, "ns", "del", {"a": 1})
    await _delete(client, headers, "ns", "del")

    r = await _at_version(client, headers, "ns", "del", 2)
    assert r.status_code == 200
    assert r.json()["operation"] == "deleted"
    assert r.json()["value"] is None


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------

async def test_rollback_restores_value(client: AsyncClient) -> None:
    """Rollback to version 1 restores the original value."""
    _, headers = await _setup(client)

    await _put(client, headers, "ns", "rb", {"v": "original"})
    await _put(client, headers, "ns", "rb", {"v": "updated"})

    r = await _rollback(client, headers, "ns", "rb", target_version=1)
    assert r.status_code == 200
    body = r.json()
    assert body["restored_version"] == 1
    assert body["new_version"] == 3
    assert body["entry"]["value"] == {"v": "original"}

    # Current live value is the restored one
    r2 = await client.get("/v1/context/ns/rb", headers=headers)
    assert r2.json()["value"] == {"v": "original"}
    assert r2.json()["version"] == 3


async def test_rollback_adds_rollback_history_entry(client: AsyncClient) -> None:
    """Rollback creates a history entry with operation=rollback."""
    _, headers = await _setup(client)

    await _put(client, headers, "ns", "rb2", {"v": 1})
    await _put(client, headers, "ns", "rb2", {"v": 2})
    await _rollback(client, headers, "ns", "rb2", target_version=1)

    r = await _history(client, headers, "ns", "rb2")
    entries = r.json()["entries"]
    assert entries[0]["operation"] == "rollback"
    assert entries[0]["version"] == 3
    assert entries[0]["value"] == {"v": 1}


async def test_rollback_after_delete_restores_key(client: AsyncClient) -> None:
    """Rollback to a pre-deletion version recreates the deleted key."""
    _, headers = await _setup(client)

    await _put(client, headers, "ns", "dead", {"alive": True})
    await _delete(client, headers, "ns", "dead")

    # Key no longer exists
    r = await client.get("/v1/context/ns/dead", headers=headers)
    assert r.status_code == 404

    # Rollback to version 1 (before deletion)
    r = await _rollback(client, headers, "ns", "dead", target_version=1)
    assert r.status_code == 200
    assert r.json()["entry"]["value"] == {"alive": True}

    # Key exists again
    r2 = await client.get("/v1/context/ns/dead", headers=headers)
    assert r2.status_code == 200
    assert r2.json()["value"] == {"alive": True}


async def test_rollback_to_deleted_version_returns_422(client: AsyncClient) -> None:
    """Rollback to a version where operation=deleted is rejected with 422."""
    _, headers = await _setup(client)

    await _put(client, headers, "ns", "nope", {"x": 1})
    await _delete(client, headers, "ns", "nope")  # version 2 = deleted

    r = await _rollback(client, headers, "ns", "nope", target_version=2)
    assert r.status_code == 422


async def test_rollback_to_nonexistent_version_returns_404(client: AsyncClient) -> None:
    """Rollback to a version that was never written returns 404."""
    _, headers = await _setup(client)

    await _put(client, headers, "ns", "miss", {"x": 1})

    r = await _rollback(client, headers, "ns", "miss", target_version=99)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Cursor pagination
# ---------------------------------------------------------------------------

async def test_history_cursor_pagination(client: AsyncClient) -> None:
    """History list paginates correctly using next_cursor."""
    _, headers = await _setup(client)

    for i in range(5):
        await _put(client, headers, "ns", "paged", {"i": i})

    # First page: 3 items
    r1 = await _history(client, headers, "ns", "paged", limit=3)
    body1 = r1.json()
    assert len(body1["entries"]) == 3
    assert body1["entries"][0]["version"] == 5  # newest first
    assert body1["next_cursor"] is not None

    # Second page: remaining 2 items
    r2 = await _history(client, headers, "ns", "paged", limit=3, cursor=body1["next_cursor"])
    body2 = r2.json()
    assert len(body2["entries"]) == 2
    assert body2["entries"][0]["version"] == 2
    assert body2["next_cursor"] is None


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------

async def test_tenant_cannot_see_other_tenant_history(client: AsyncClient) -> None:
    """History for one tenant's key is invisible to another tenant."""
    _, h1 = await _setup(client)
    _, h2 = await _setup(client)

    await _put(client, h1, "ns", "secret", {"data": "private"})

    # Tenant 2 sees no history for that key
    r = await _history(client, h2, "ns", "secret")
    assert r.status_code == 200
    assert r.json()["entries"] == []


async def test_tenant_cannot_rollback_other_tenant_key(client: AsyncClient) -> None:
    """Rollback by tenant 2 on a key owned by tenant 1 returns 404 (no history found)."""
    _, h1 = await _setup(client)
    _, h2 = await _setup(client)

    await _put(client, h1, "ns", "own", {"v": 1})

    # Tenant 2 tries to rollback tenant 1's key version 1 → 404 (no version in their history)
    r = await _rollback(client, h2, "ns", "own", target_version=1)
    assert r.status_code == 404


async def test_same_namespace_key_different_tenants_independent_history(
    client: AsyncClient,
) -> None:
    """Two tenants can use the same namespace/key — their histories are independent."""
    _, h1 = await _setup(client)
    _, h2 = await _setup(client)

    await _put(client, h1, "shared", "config", {"owner": "t1"})
    await _put(client, h1, "shared", "config", {"owner": "t1-v2"})
    await _put(client, h2, "shared", "config", {"owner": "t2"})

    r1 = await _history(client, h1, "shared", "config")
    r2 = await _history(client, h2, "shared", "config")

    assert len(r1.json()["entries"]) == 2
    assert len(r2.json()["entries"]) == 1
    assert r2.json()["entries"][0]["value"] == {"owner": "t2"}
