"""Session management tests: create, close, archive, validation, tenant isolation."""
import uuid

import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _setup(client: AsyncClient) -> tuple[dict, dict]:
    r = await client.post("/v1/tenants", json={"name": f"SessionCo-{uuid.uuid4()}"})
    assert r.status_code == 201
    tenant = r.json()
    return tenant, {"X-API-Key": tenant["initial_api_key"]}


async def _create_agent(client: AsyncClient, headers: dict) -> dict:
    r = await client.post(
        "/v1/agents",
        json={"name": f"bot-{uuid.uuid4()}", "description": "test"},
        headers=headers,
    )
    assert r.status_code == 201
    return r.json()


async def _create_session(client: AsyncClient, headers: dict, agent_id: str) -> dict:
    r = await client.post(
        "/v1/sessions",
        json={"agent_id": agent_id},
        headers=headers,
    )
    assert r.status_code == 201
    return r.json()


# ---------------------------------------------------------------------------
# Basic CRUD
# ---------------------------------------------------------------------------

async def test_create_session_returns_active(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)

    r = await client.post("/v1/sessions", json={"agent_id": agent["id"]}, headers=headers)

    assert r.status_code == 201
    data = r.json()
    assert data["status"] == "active"
    assert data["agent_id"] == agent["id"]
    assert data["message_count"] == 0
    assert data["closed_at"] is None


async def test_create_session_unknown_agent_returns_404(client: AsyncClient) -> None:
    _, headers = await _setup(client)

    r = await client.post("/v1/sessions", json={"agent_id": str(uuid.uuid4())}, headers=headers)

    assert r.status_code == 404


async def test_get_session(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    sess = await _create_session(client, headers, agent["id"])

    r = await client.get(f"/v1/sessions/{sess['id']}", headers=headers)

    assert r.status_code == 200
    assert r.json()["id"] == sess["id"]


async def test_get_session_not_found(client: AsyncClient) -> None:
    _, headers = await _setup(client)

    r = await client.get(f"/v1/sessions/{uuid.uuid4()}", headers=headers)

    assert r.status_code == 404


async def test_list_sessions(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    await _create_session(client, headers, agent["id"])
    await _create_session(client, headers, agent["id"])

    r = await client.get("/v1/sessions", headers=headers)

    assert r.status_code == 200
    assert len(r.json()) == 2


async def test_list_sessions_filter_by_status(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    sess = await _create_session(client, headers, agent["id"])
    await _create_session(client, headers, agent["id"])

    with patch(
        "crewlayer.core.memory.extractor._client",
        AsyncMock(**{"messages.create": AsyncMock(
            return_value=AsyncMock(content=[AsyncMock(text="[]")])
        )}),
    ):
        await client.post(f"/v1/sessions/{sess['id']}/close", headers=headers)

    r = await client.get("/v1/sessions?status=active", headers=headers)
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = await client.get("/v1/sessions?status=closed", headers=headers)
    assert r.status_code == 200
    assert len(r.json()) == 1


# ---------------------------------------------------------------------------
# Close session
# ---------------------------------------------------------------------------

async def test_close_session_changes_status(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    sess = await _create_session(client, headers, agent["id"])

    with patch(
        "crewlayer.core.memory.extractor._client",
        AsyncMock(**{"messages.create": AsyncMock(
            return_value=AsyncMock(content=[AsyncMock(text="[]")])
        )}),
    ):
        r = await client.post(f"/v1/sessions/{sess['id']}/close", headers=headers)

    assert r.status_code == 200
    data = r.json()
    assert data["session"]["status"] == "closed"
    assert data["session"]["closed_at"] is not None


async def test_close_session_extracts_memories(client: AsyncClient) -> None:
    """Full cycle: create session, append messages, close — memories get extracted."""
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    sess = await _create_session(client, headers, agent["id"])
    session_id = sess["id"]

    # Append two messages using the session UUID as session_id
    await client.post(
        f"/v1/agents/{agent['id']}/memory/messages?session_id={session_id}",
        json={"role": "user", "content": "My name is Alice"},
        headers=headers,
    )
    await client.post(
        f"/v1/agents/{agent['id']}/memory/messages?session_id={session_id}",
        json={"role": "assistant", "content": "Hello Alice!"},
        headers=headers,
    )

    extracted_fact = [{"content": "User's name is Alice", "importance": 0.9, "tags": ["name"]}]
    import json

    with patch(
        "crewlayer.core.memory.extractor._client",
        AsyncMock(**{"messages.create": AsyncMock(
            return_value=AsyncMock(
                content=[AsyncMock(text=json.dumps(extracted_fact))]
            )
        )}),
    ):
        with patch("crewlayer.core.memory.long.get_embedding", new=AsyncMock(return_value=[0.1] * 1536)):
            r = await client.post(f"/v1/sessions/{session_id}/close", headers=headers)

    assert r.status_code == 200
    assert r.json()["session"]["message_count"] == 2


async def test_close_already_closed_session_returns_409(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    sess = await _create_session(client, headers, agent["id"])

    with patch(
        "crewlayer.core.memory.extractor._client",
        AsyncMock(**{"messages.create": AsyncMock(
            return_value=AsyncMock(content=[AsyncMock(text="[]")])
        )}),
    ):
        await client.post(f"/v1/sessions/{sess['id']}/close", headers=headers)
        r = await client.post(f"/v1/sessions/{sess['id']}/close", headers=headers)

    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Archive session
# ---------------------------------------------------------------------------

async def test_archive_closed_session(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    sess = await _create_session(client, headers, agent["id"])

    with patch(
        "crewlayer.core.memory.extractor._client",
        AsyncMock(**{"messages.create": AsyncMock(
            return_value=AsyncMock(content=[AsyncMock(text="[]")])
        )}),
    ):
        await client.post(f"/v1/sessions/{sess['id']}/close", headers=headers)

    r = await client.post(f"/v1/sessions/{sess['id']}/archive", headers=headers)

    assert r.status_code == 200
    assert r.json()["status"] == "archived"


async def test_archive_active_session_returns_409(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    sess = await _create_session(client, headers, agent["id"])

    r = await client.post(f"/v1/sessions/{sess['id']}/archive", headers=headers)

    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Session validation in memory + actions routes
# ---------------------------------------------------------------------------

async def test_append_message_to_closed_session_returns_409(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    sess = await _create_session(client, headers, agent["id"])

    with patch(
        "crewlayer.core.memory.extractor._client",
        AsyncMock(**{"messages.create": AsyncMock(
            return_value=AsyncMock(content=[AsyncMock(text="[]")])
        )}),
    ):
        await client.post(f"/v1/sessions/{sess['id']}/close", headers=headers)

    r = await client.post(
        f"/v1/agents/{agent['id']}/memory/messages?session_id={sess['id']}",
        json={"role": "user", "content": "This should fail"},
        headers=headers,
    )

    assert r.status_code == 409


async def test_log_action_to_closed_session_returns_409(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    sess = await _create_session(client, headers, agent["id"])

    with patch(
        "crewlayer.core.memory.extractor._client",
        AsyncMock(**{"messages.create": AsyncMock(
            return_value=AsyncMock(content=[AsyncMock(text="[]")])
        )}),
    ):
        await client.post(f"/v1/sessions/{sess['id']}/close", headers=headers)

    r = await client.post(
        f"/v1/agents/{agent['id']}/actions",
        json={
            "tool_name": "search",
            "input_params": {},
            "output_result": {},
            "status": "success",
            "session_id": sess["id"],
        },
        headers=headers,
    )

    assert r.status_code == 409


async def test_append_message_string_session_id_skips_validation(client: AsyncClient) -> None:
    """Non-UUID session_id bypasses validation for backward compatibility."""
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)

    r = await client.post(
        f"/v1/agents/{agent['id']}/memory/messages?session_id=default",
        json={"role": "user", "content": "hello"},
        headers=headers,
    )

    assert r.status_code == 201


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------

async def test_session_tenant_isolation(client: AsyncClient) -> None:
    _, headers_a = await _setup(client)
    _, headers_b = await _setup(client)
    agent_a = await _create_agent(client, headers_a)
    sess_a = await _create_session(client, headers_a, agent_a["id"])

    r = await client.get(f"/v1/sessions/{sess_a['id']}", headers=headers_b)

    assert r.status_code == 404


async def test_list_sessions_tenant_isolation(client: AsyncClient) -> None:
    _, headers_a = await _setup(client)
    _, headers_b = await _setup(client)
    agent_a = await _create_agent(client, headers_a)
    await _create_session(client, headers_a, agent_a["id"])

    r = await client.get("/v1/sessions", headers=headers_b)

    assert r.status_code == 200
    assert r.json() == []
