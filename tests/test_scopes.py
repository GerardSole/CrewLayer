"""Granular scope and agent_ids restriction tests for API keys."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

_FAKE_EMBED = [1.0] + [0.0] * 1535


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_tenant(client: AsyncClient) -> tuple[dict, str]:
    """Create a tenant and return (tenant_json, bootstrap_key)."""
    r = await client.post("/v1/tenants", json={"name": f"ScopeCo-{uuid.uuid4()}"})
    assert r.status_code == 201
    data = r.json()
    return data, data["initial_api_key"]


async def _create_agent(client: AsyncClient, headers: dict) -> dict:
    r = await client.post("/v1/agents", json={"name": "scope-agent"}, headers=headers)
    assert r.status_code == 201
    return r.json()


async def _create_key(
    client: AsyncClient,
    headers: dict,
    *,
    scopes: list[str],
    agent_ids: list[str] | None = None,
) -> str:
    """Create an API key with specific scopes and optional agent_ids; return raw key."""
    body: dict = {"name": f"key-{uuid.uuid4()}", "scopes": scopes}
    if agent_ids is not None:
        body["agent_ids"] = agent_ids
    r = await client.post("/v1/api-keys", json=body, headers=headers)
    assert r.status_code == 201, r.json()
    return r.json()["key"]


# ---------------------------------------------------------------------------
# Scope validation on creation
# ---------------------------------------------------------------------------

async def test_create_key_with_valid_scopes_succeeds(client: AsyncClient) -> None:
    _, admin_key = await _create_tenant(client)
    headers = {"X-API-Key": admin_key}
    r = await client.post(
        "/v1/api-keys",
        json={"name": "test", "scopes": ["memory:read", "memory:write"]},
        headers=headers,
    )
    assert r.status_code == 201
    assert r.json()["scopes"] == ["memory:read", "memory:write"]


async def test_create_key_with_invalid_scope_returns_422(client: AsyncClient) -> None:
    _, admin_key = await _create_tenant(client)
    headers = {"X-API-Key": admin_key}
    r = await client.post(
        "/v1/api-keys",
        json={"name": "bad", "scopes": ["bogus:scope"]},
        headers=headers,
    )
    assert r.status_code == 422


async def test_create_key_with_agent_ids_returned_in_response(client: AsyncClient) -> None:
    _, admin_key = await _create_tenant(client)
    headers = {"X-API-Key": admin_key}
    agent = await _create_agent(client, headers)
    r = await client.post(
        "/v1/api-keys",
        json={"name": "restricted", "scopes": ["memory:read"], "agent_ids": [agent["id"]]},
        headers=headers,
    )
    assert r.status_code == 201
    assert agent["id"] in r.json()["agent_ids"]


# ---------------------------------------------------------------------------
# Full-access key (empty scopes) passes everything
# ---------------------------------------------------------------------------

async def test_full_access_key_can_recall(client: AsyncClient) -> None:
    _, admin_key = await _create_tenant(client)
    headers = {"X-API-Key": admin_key}
    agent = await _create_agent(client, headers)

    with patch("crewlayer.core.memory.long.get_embedding", AsyncMock(return_value=_FAKE_EMBED)):
        r = await client.post(
            f"/v1/agents/{agent['id']}/memory/recall",
            json={"query": "test"},
            headers=headers,
        )
    assert r.status_code == 200


async def test_full_access_key_can_list_agents(client: AsyncClient) -> None:
    _, admin_key = await _create_tenant(client)
    r = await client.get("/v1/agents", headers={"X-API-Key": admin_key})
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Correct scope passes
# ---------------------------------------------------------------------------

async def test_memory_read_scope_allows_recall(client: AsyncClient) -> None:
    _, admin_key = await _create_tenant(client)
    headers = {"X-API-Key": admin_key}
    agent = await _create_agent(client, headers)
    scoped_key = await _create_key(client, headers, scopes=["memory:read"])

    with patch("crewlayer.core.memory.long.get_embedding", AsyncMock(return_value=_FAKE_EMBED)):
        r = await client.post(
            f"/v1/agents/{agent['id']}/memory/recall",
            json={"query": "hello"},
            headers={"X-API-Key": scoped_key},
        )
    assert r.status_code == 200


async def test_memory_read_scope_allows_list(client: AsyncClient) -> None:
    _, admin_key = await _create_tenant(client)
    headers = {"X-API-Key": admin_key}
    agent = await _create_agent(client, headers)
    scoped_key = await _create_key(client, headers, scopes=["memory:read"])

    r = await client.get(
        f"/v1/agents/{agent['id']}/memory",
        headers={"X-API-Key": scoped_key},
    )
    assert r.status_code == 200


async def test_agents_read_scope_allows_list(client: AsyncClient) -> None:
    _, admin_key = await _create_tenant(client)
    headers = {"X-API-Key": admin_key}
    scoped_key = await _create_key(client, headers, scopes=["agents:read"])

    r = await client.get("/v1/agents", headers={"X-API-Key": scoped_key})
    assert r.status_code == 200


async def test_actions_read_scope_allows_list(client: AsyncClient) -> None:
    _, admin_key = await _create_tenant(client)
    headers = {"X-API-Key": admin_key}
    agent = await _create_agent(client, headers)
    scoped_key = await _create_key(client, headers, scopes=["actions:read"])

    r = await client.get(
        f"/v1/agents/{agent['id']}/actions",
        headers={"X-API-Key": scoped_key},
    )
    assert r.status_code == 200


async def test_context_read_scope_allows_read(client: AsyncClient) -> None:
    _, admin_key = await _create_tenant(client)
    headers = {"X-API-Key": admin_key}
    # Write first with admin key
    await client.put("/v1/context/ns/k", json={"value": {"x": 1}}, headers=headers)
    scoped_key = await _create_key(client, headers, scopes=["context:read"])

    r = await client.get("/v1/context/ns/k", headers={"X-API-Key": scoped_key})
    assert r.status_code == 200


async def test_sessions_read_scope_allows_list(client: AsyncClient) -> None:
    _, admin_key = await _create_tenant(client)
    headers = {"X-API-Key": admin_key}
    scoped_key = await _create_key(client, headers, scopes=["sessions:read"])

    r = await client.get("/v1/sessions", headers={"X-API-Key": scoped_key})
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Wrong / missing scope returns 403
# ---------------------------------------------------------------------------

async def test_missing_memory_read_scope_blocks_recall(client: AsyncClient) -> None:
    _, admin_key = await _create_tenant(client)
    headers = {"X-API-Key": admin_key}
    agent = await _create_agent(client, headers)
    # Key has actions:read only — no memory:read
    scoped_key = await _create_key(client, headers, scopes=["actions:read"])

    with patch("crewlayer.core.memory.long.get_embedding", AsyncMock(return_value=_FAKE_EMBED)):
        r = await client.post(
            f"/v1/agents/{agent['id']}/memory/recall",
            json={"query": "hello"},
            headers={"X-API-Key": scoped_key},
        )
    assert r.status_code == 403


async def test_missing_memory_write_scope_blocks_extract(client: AsyncClient) -> None:
    _, admin_key = await _create_tenant(client)
    headers = {"X-API-Key": admin_key}
    agent = await _create_agent(client, headers)
    scoped_key = await _create_key(client, headers, scopes=["memory:read"])

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="[]")]
    with (
        patch("crewlayer.core.memory.long.get_embedding", AsyncMock(return_value=_FAKE_EMBED)),
        patch(
            "crewlayer.core.memory.extractor._client.messages.create",
            AsyncMock(return_value=mock_response),
        ),
    ):
        r = await client.post(
            f"/v1/agents/{agent['id']}/memory/extract",
            json={"conversation": "hello"},
            headers={"X-API-Key": scoped_key},
        )
    assert r.status_code == 403


async def test_missing_agents_read_scope_blocks_list(client: AsyncClient) -> None:
    _, admin_key = await _create_tenant(client)
    headers = {"X-API-Key": admin_key}
    # Key with memory:read but no agents:read
    scoped_key = await _create_key(client, headers, scopes=["memory:read"])

    r = await client.get("/v1/agents", headers={"X-API-Key": scoped_key})
    assert r.status_code == 403


async def test_missing_context_write_scope_blocks_write(client: AsyncClient) -> None:
    _, admin_key = await _create_tenant(client)
    headers = {"X-API-Key": admin_key}
    scoped_key = await _create_key(client, headers, scopes=["context:read"])

    r = await client.put(
        "/v1/context/ns/k",
        json={"value": {"x": 1}},
        headers={"X-API-Key": scoped_key},
    )
    assert r.status_code == 403


async def test_missing_actions_write_scope_blocks_log(client: AsyncClient) -> None:
    _, admin_key = await _create_tenant(client)
    headers = {"X-API-Key": admin_key}
    agent = await _create_agent(client, headers)
    scoped_key = await _create_key(client, headers, scopes=["actions:read"])

    r = await client.post(
        f"/v1/agents/{agent['id']}/actions",
        json={
            "tool_name": "test_tool",
            "input_params": {},
            "output_result": {},
            "status": "success",
        },
        headers={"X-API-Key": scoped_key},
    )
    assert r.status_code == 403


async def test_missing_sessions_write_scope_blocks_create(client: AsyncClient) -> None:
    _, admin_key = await _create_tenant(client)
    headers = {"X-API-Key": admin_key}
    agent = await _create_agent(client, headers)
    scoped_key = await _create_key(client, headers, scopes=["sessions:read"])

    r = await client.post(
        "/v1/sessions",
        json={"agent_id": agent["id"]},
        headers={"X-API-Key": scoped_key},
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# agent_ids restriction
# ---------------------------------------------------------------------------

async def test_key_limited_to_agent_allows_that_agent(client: AsyncClient) -> None:
    _, admin_key = await _create_tenant(client)
    headers = {"X-API-Key": admin_key}
    agent = await _create_agent(client, headers)
    scoped_key = await _create_key(
        client, headers,
        scopes=["memory:read"],
        agent_ids=[agent["id"]],
    )

    with patch("crewlayer.core.memory.long.get_embedding", AsyncMock(return_value=_FAKE_EMBED)):
        r = await client.post(
            f"/v1/agents/{agent['id']}/memory/recall",
            json={"query": "test"},
            headers={"X-API-Key": scoped_key},
        )
    assert r.status_code == 200


async def test_key_limited_to_agent_blocks_other_agent(client: AsyncClient) -> None:
    _, admin_key = await _create_tenant(client)
    headers = {"X-API-Key": admin_key}
    agent_a = await _create_agent(client, headers)
    agent_b = await _create_agent(client, headers)

    # Key is restricted to agent_a only
    scoped_key = await _create_key(
        client, headers,
        scopes=["memory:read"],
        agent_ids=[agent_a["id"]],
    )

    with patch("crewlayer.core.memory.long.get_embedding", AsyncMock(return_value=_FAKE_EMBED)):
        r = await client.post(
            f"/v1/agents/{agent_b['id']}/memory/recall",
            json={"query": "test"},
            headers={"X-API-Key": scoped_key},
        )
    assert r.status_code == 403


async def test_key_with_agent_ids_blocks_actions_on_other_agent(client: AsyncClient) -> None:
    _, admin_key = await _create_tenant(client)
    headers = {"X-API-Key": admin_key}
    agent_a = await _create_agent(client, headers)
    agent_b = await _create_agent(client, headers)

    scoped_key = await _create_key(
        client, headers,
        scopes=["actions:read"],
        agent_ids=[agent_a["id"]],
    )

    r = await client.get(
        f"/v1/agents/{agent_b['id']}/actions",
        headers={"X-API-Key": scoped_key},
    )
    assert r.status_code == 403


async def test_key_without_agent_ids_can_access_any_agent(client: AsyncClient) -> None:
    _, admin_key = await _create_tenant(client)
    headers = {"X-API-Key": admin_key}
    agent = await _create_agent(client, headers)

    # Scoped key with no agent_ids restriction
    scoped_key = await _create_key(client, headers, scopes=["memory:read"])

    with patch("crewlayer.core.memory.long.get_embedding", AsyncMock(return_value=_FAKE_EMBED)):
        r = await client.post(
            f"/v1/agents/{agent['id']}/memory/recall",
            json={"query": "test"},
            headers={"X-API-Key": scoped_key},
        )
    assert r.status_code == 200


async def test_agent_ids_listed_in_api_keys_response(client: AsyncClient) -> None:
    _, admin_key = await _create_tenant(client)
    headers = {"X-API-Key": admin_key}
    agent = await _create_agent(client, headers)

    await _create_key(
        client, headers,
        scopes=["memory:read"],
        agent_ids=[agent["id"]],
    )

    r = await client.get("/v1/api-keys", headers=headers)
    assert r.status_code == 200
    restricted = [k for k in r.json() if k["agent_ids"]]
    assert len(restricted) >= 1
    assert agent["id"] in restricted[0]["agent_ids"]
