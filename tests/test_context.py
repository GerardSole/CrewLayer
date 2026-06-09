"""Blackboard / context tests: write, read, version conflict, expiry, namespace list, tenant isolation."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _setup(client: AsyncClient) -> tuple[dict, dict]:
    """Create a tenant; return (tenant, headers)."""
    r = await client.post("/v1/tenants", json={"name": f"CtxCo-{uuid.uuid4()}"})
    assert r.status_code == 201
    tenant = r.json()
    headers = {"X-API-Key": tenant["initial_api_key"]}
    return tenant, headers


async def _put(client, headers, ns, key, value, **extra) -> dict:
    r = await client.put(
        f"/v1/context/{ns}/{key}",
        json={"value": value, **extra},
        headers=headers,
    )
    return r


# ---------------------------------------------------------------------------
# Write and read
# ---------------------------------------------------------------------------

async def test_write_creates_entry_with_version_1(client: AsyncClient) -> None:
    _, headers = await _setup(client)

    r = await _put(client, headers, "agents", "config", {"model": "gpt-4"})

    assert r.status_code == 200
    data = r.json()
    assert data["namespace"] == "agents"
    assert data["key"] == "config"
    assert data["value"] == {"model": "gpt-4"}
    assert data["version"] == 1


async def test_read_returns_written_value(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    await _put(client, headers, "shared", "prompt", {"text": "Hello"})

    r = await client.get("/v1/context/shared/prompt", headers=headers)

    assert r.status_code == 200
    assert r.json()["value"] == {"text": "Hello"}


async def test_overwrite_increments_version(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    await _put(client, headers, "ns", "k", {"v": 1})

    r = await _put(client, headers, "ns", "k", {"v": 2})

    assert r.status_code == 200
    assert r.json()["version"] == 2
    assert r.json()["value"] == {"v": 2}


async def test_read_absent_key_returns_404(client: AsyncClient) -> None:
    _, headers = await _setup(client)

    r = await client.get("/v1/context/nothing/here", headers=headers)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Optimistic locking
# ---------------------------------------------------------------------------

async def test_write_with_correct_expected_version_succeeds(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    await _put(client, headers, "lock", "x", {"a": 1})  # version=1

    r = await _put(client, headers, "lock", "x", {"a": 2}, expected_version=1)

    assert r.status_code == 200
    assert r.json()["version"] == 2


async def test_write_with_wrong_expected_version_returns_409(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    await _put(client, headers, "lock", "y", {"a": 1})  # version=1

    r = await _put(client, headers, "lock", "y", {"a": 2}, expected_version=99)

    assert r.status_code == 409
    assert "conflict" in r.json()["detail"].lower()


async def test_expected_version_0_fails_when_key_exists(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    await _put(client, headers, "lock", "existing", {"a": 1})  # already exists

    r = await _put(client, headers, "lock", "existing", {"a": 2}, expected_version=0)

    assert r.status_code == 409


async def test_expected_version_0_succeeds_for_new_key(client: AsyncClient) -> None:
    _, headers = await _setup(client)

    r = await _put(client, headers, "lock", "brand-new", {"a": 1}, expected_version=0)

    assert r.status_code == 200
    assert r.json()["version"] == 1


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

async def test_delete_removes_entry(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    await _put(client, headers, "d", "gone", {"x": 1})

    r = await client.delete("/v1/context/d/gone", headers=headers)
    assert r.status_code == 204

    r = await client.get("/v1/context/d/gone", headers=headers)
    assert r.status_code == 404


async def test_delete_nonexistent_returns_404(client: AsyncClient) -> None:
    _, headers = await _setup(client)

    r = await client.delete("/v1/context/missing/key", headers=headers)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Namespace listing
# ---------------------------------------------------------------------------

async def test_list_namespace_returns_all_keys(client: AsyncClient) -> None:
    _, headers = await _setup(client)

    for key in ["a", "b", "c"]:
        await _put(client, headers, "myns", key, {"val": key})

    r = await client.get("/v1/context/myns", headers=headers)

    assert r.status_code == 200
    data = r.json()
    assert data["namespace"] == "myns"
    assert data["count"] == 3
    keys = [e["key"] for e in data["entries"]]
    assert keys == sorted(keys)  # ordered by key


async def test_list_empty_namespace_returns_zero(client: AsyncClient) -> None:
    _, headers = await _setup(client)

    r = await client.get("/v1/context/empty-ns", headers=headers)

    assert r.status_code == 200
    assert r.json()["count"] == 0


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------

async def test_expired_entry_not_readable(client: AsyncClient) -> None:
    _, headers = await _setup(client)

    past = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    r = await _put(client, headers, "exp", "stale", {"x": 1}, expires_at=past)
    assert r.status_code == 200

    r = await client.get("/v1/context/exp/stale", headers=headers)
    assert r.status_code == 404


async def test_expired_entry_excluded_from_list(client: AsyncClient) -> None:
    _, headers = await _setup(client)

    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    past = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()

    await _put(client, headers, "mixed", "live", {"ok": True}, expires_at=future)
    await _put(client, headers, "mixed", "dead", {"ok": False}, expires_at=past)

    r = await client.get("/v1/context/mixed", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert data["entries"][0]["key"] == "live"


async def test_non_expiring_entry_always_readable(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    await _put(client, headers, "perm", "forever", {"immortal": True})

    r = await client.get("/v1/context/perm/forever", headers=headers)
    assert r.status_code == 200
    assert r.json()["expires_at"] is None


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------

async def test_tenant_cannot_read_foreign_context(client: AsyncClient) -> None:
    _, headers_a = await _setup(client)
    _, headers_b = await _setup(client)

    await _put(client, headers_a, "secret", "key", {"data": "private"})

    r = await client.get("/v1/context/secret/key", headers=headers_b)
    assert r.status_code == 404


async def test_tenant_list_shows_only_own_entries(client: AsyncClient) -> None:
    _, headers_a = await _setup(client)
    _, headers_b = await _setup(client)

    await _put(client, headers_a, "shared-ns", "a-key", {"owner": "a"})
    await _put(client, headers_b, "shared-ns", "b-key", {"owner": "b"})

    r_a = await client.get("/v1/context/shared-ns", headers=headers_a)
    r_b = await client.get("/v1/context/shared-ns", headers=headers_b)

    assert r_a.json()["count"] == 1
    assert r_a.json()["entries"][0]["key"] == "a-key"
    assert r_b.json()["count"] == 1
    assert r_b.json()["entries"][0]["key"] == "b-key"


async def test_tenant_cannot_delete_foreign_context(client: AsyncClient) -> None:
    _, headers_a = await _setup(client)
    _, headers_b = await _setup(client)

    await _put(client, headers_a, "protected", "val", {"x": 1})

    r = await client.delete("/v1/context/protected/val", headers=headers_b)
    assert r.status_code == 404

    # Entry still exists for tenant A
    r = await client.get("/v1/context/protected/val", headers=headers_a)
    assert r.status_code == 200
