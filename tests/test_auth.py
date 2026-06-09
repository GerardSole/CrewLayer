"""Auth system tests: tenants, API keys, authentication."""
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_tenant(client: AsyncClient, name: str = "TestCo") -> dict:
    r = await client.post("/v1/tenants", json={"name": name})
    assert r.status_code == 201
    return r.json()


async def _auth_headers(client: AsyncClient, name: str = "TestCo") -> tuple[dict, dict]:
    """Return (tenant_data, headers) with a valid X-API-Key."""
    tenant = await _create_tenant(client, name)
    headers = {"X-API-Key": tenant["initial_api_key"]}
    return tenant, headers


# ---------------------------------------------------------------------------
# Tenant creation
# ---------------------------------------------------------------------------

async def test_create_tenant_returns_tenant_and_bootstrap_key(client: AsyncClient) -> None:
    r = await client.post("/v1/tenants", json={"name": "Acme Corp"})

    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Acme Corp"
    assert data["plan"] == "free"
    assert "id" in data
    assert "created_at" in data
    # Bootstrap key is present and has the expected format crwl_{uuid32hex}_{secret}
    key = data["initial_api_key"]
    assert key.startswith("crwl_")
    parts = key.split("_", 2)   # max-split=2 because the secret may itself contain '_'
    assert len(parts) == 3
    assert len(parts[1]) == 32  # UUID without dashes is 32 hex chars


# ---------------------------------------------------------------------------
# API key creation
# ---------------------------------------------------------------------------

async def test_create_api_key_returns_raw_key_once(client: AsyncClient) -> None:
    _, headers = await _auth_headers(client)

    r = await client.post(
        "/v1/api-keys",
        json={"name": "production", "scopes": ["memory:read", "memory:write"]},
        headers=headers,
    )

    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "production"
    assert data["scopes"] == ["memory:read", "memory:write"]
    assert data["key"].startswith("crwl_")
    assert "key_hash" not in data  # hash must never be exposed


async def test_create_api_key_without_auth_returns_401(client: AsyncClient) -> None:
    r = await client.post("/v1/api-keys", json={"name": "bad"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Authentication — valid key
# ---------------------------------------------------------------------------

async def test_authenticate_with_valid_key(client: AsyncClient) -> None:
    _, headers = await _auth_headers(client)

    r = await client.get("/v1/api-keys", headers=headers)

    assert r.status_code == 200
    keys = r.json()
    # At minimum the bootstrap key is listed
    assert any(k["name"] == "default" for k in keys)


# ---------------------------------------------------------------------------
# Authentication — invalid key
# ---------------------------------------------------------------------------

async def test_reject_missing_header(client: AsyncClient) -> None:
    r = await client.get("/v1/api-keys")
    assert r.status_code == 401


async def test_reject_malformed_key(client: AsyncClient) -> None:
    r = await client.get("/v1/api-keys", headers={"X-API-Key": "not-a-valid-key-format"})
    assert r.status_code == 401


async def test_reject_key_with_wrong_secret(client: AsyncClient) -> None:
    """Key ID exists but secret doesn't match."""
    tenant = await _create_tenant(client)
    real_key: str = tenant["initial_api_key"]
    # Swap the secret part with garbage while keeping a valid key_id prefix
    prefix = "_".join(real_key.split("_", 2)[:2])
    tampered = f"{prefix}_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"

    r = await client.get("/v1/api-keys", headers={"X-API-Key": tampered})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Cross-tenant isolation
# ---------------------------------------------------------------------------

async def test_key_of_other_tenant_cannot_revoke_foreign_key(client: AsyncClient) -> None:
    """Tenant B cannot revoke a key that belongs to tenant A."""
    _, headers_a = await _auth_headers(client, "Tenant A")
    _, headers_b = await _auth_headers(client, "Tenant B")

    # Tenant A creates an extra key
    r = await client.post(
        "/v1/api-keys", json={"name": "a-key"}, headers=headers_a
    )
    key_a_id = r.json()["id"]
    key_a_raw = r.json()["key"]

    # Tenant B tries to delete it — must get 404 (not 403 to avoid leaking existence)
    r = await client.delete(f"/v1/api-keys/{key_a_id}", headers=headers_b)
    assert r.status_code == 404

    # Tenant A's key still works after the failed deletion attempt
    r = await client.get("/v1/api-keys", headers={"X-API-Key": key_a_raw})
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Key revocation
# ---------------------------------------------------------------------------

async def test_revoke_key_then_reject_it(client: AsyncClient) -> None:
    """A revoked key must be rejected on subsequent requests."""
    _, headers = await _auth_headers(client)

    # Create a second key
    r = await client.post("/v1/api-keys", json={"name": "temp"}, headers=headers)
    assert r.status_code == 201
    temp_id = r.json()["id"]
    temp_key = r.json()["key"]

    # Revoke using the original key
    r = await client.delete(f"/v1/api-keys/{temp_id}", headers=headers)
    assert r.status_code == 204

    # Revoked key must now be rejected
    r = await client.get("/v1/api-keys", headers={"X-API-Key": temp_key})
    assert r.status_code == 401


async def test_list_keys_does_not_expose_hash(client: AsyncClient) -> None:
    _, headers = await _auth_headers(client)

    r = await client.get("/v1/api-keys", headers=headers)
    assert r.status_code == 200
    for key in r.json():
        assert "key_hash" not in key
        assert "key" not in key
