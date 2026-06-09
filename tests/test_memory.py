"""Memory engine tests: short memory (Redis), long memory (pgvector), recall, and extract."""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

_FAKE_EMBEDDING = [0.1] * 1536


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _setup(client: AsyncClient) -> tuple[dict, dict, dict]:
    """Create a tenant + agent and return (tenant, agent, headers)."""
    r = await client.post("/v1/tenants", json={"name": f"MemCo-{uuid.uuid4()}"})
    assert r.status_code == 201
    tenant = r.json()
    headers = {"X-API-Key": tenant["initial_api_key"]}

    r = await client.post("/v1/agents", json={"name": "mem-agent"}, headers=headers)
    assert r.status_code == 201
    agent = r.json()

    return tenant, agent, headers


# ---------------------------------------------------------------------------
# Short memory
# ---------------------------------------------------------------------------

async def test_append_message_creates_session(client: AsyncClient, mocker) -> None:
    _, agent, headers = await _setup(client)

    r = await client.post(
        f"/v1/agents/{agent['id']}/memory/messages",
        json={"role": "user", "content": "Hello, world!"},
        headers=headers,
        params={"session_id": "sess-1"},
    )

    assert r.status_code == 201
    data = r.json()
    assert data["session_id"] == "sess-1"
    assert data["count"] == 1
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][0]["content"] == "Hello, world!"


async def test_get_messages_returns_in_reverse_order(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)

    for role, content in [("user", "First"), ("assistant", "Second"), ("user", "Third")]:
        await client.post(
            f"/v1/agents/{agent['id']}/memory/messages",
            json={"role": role, "content": content},
            headers=headers,
            params={"session_id": "sess-order"},
        )

    r = await client.get(
        f"/v1/agents/{agent['id']}/memory/messages",
        headers=headers,
        params={"session_id": "sess-order"},
    )

    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert len(msgs) == 3
    # Newest first (LPUSH order)
    assert msgs[0]["content"] == "Third"
    assert msgs[2]["content"] == "First"


async def test_short_memory_session_isolation(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)

    await client.post(
        f"/v1/agents/{agent['id']}/memory/messages",
        json={"role": "user", "content": "Session A message"},
        headers=headers,
        params={"session_id": "sess-a"},
    )

    r = await client.get(
        f"/v1/agents/{agent['id']}/memory/messages",
        headers=headers,
        params={"session_id": "sess-b"},
    )

    assert r.status_code == 200
    assert r.json()["count"] == 0


# ---------------------------------------------------------------------------
# Long memory — recall
# ---------------------------------------------------------------------------

async def test_recall_returns_saved_memory(client: AsyncClient, mocker) -> None:
    mocker.patch(
        "crewlayer.core.memory.long.get_embedding",
        new=AsyncMock(return_value=_FAKE_EMBEDDING),
    )
    _, agent, headers = await _setup(client)

    # Save a memory via the extract endpoint using a mocked extractor
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(text='[{"content": "User loves async Python", "importance": 0.9, "tags": ["python"]}]')
    ]
    mocker.patch(
        "crewlayer.core.memory.extractor._client.messages.create",
        new=AsyncMock(return_value=mock_response),
    )

    r = await client.post(
        f"/v1/agents/{agent['id']}/memory/extract",
        json={"conversation": "I really love writing async Python code!"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["extracted_count"] == 1

    # Now recall it
    r = await client.post(
        f"/v1/agents/{agent['id']}/memory/recall",
        json={"query": "Python programming preferences", "limit": 5},
        headers=headers,
    )

    assert r.status_code == 200
    data = r.json()
    assert len(data["results"]) >= 1
    assert data["results"][0]["content"] == "User loves async Python"
    assert data["results"][0]["similarity"] is not None


async def test_recall_empty_when_no_memories(client: AsyncClient, mocker) -> None:
    mocker.patch(
        "crewlayer.core.memory.long.get_embedding",
        new=AsyncMock(return_value=_FAKE_EMBEDDING),
    )
    _, agent, headers = await _setup(client)

    r = await client.post(
        f"/v1/agents/{agent['id']}/memory/recall",
        json={"query": "something"},
        headers=headers,
    )

    assert r.status_code == 200
    assert r.json()["results"] == []


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------

async def test_extract_persists_multiple_facts(client: AsyncClient, mocker) -> None:
    # Each fact gets a distinct embedding so no merge is triggered
    _embed_a = [1.0] + [0.0] * 1535
    _embed_b = [0.0, 1.0] + [0.0] * 1534
    mocker.patch(
        "crewlayer.core.memory.long.get_embedding",
        new=AsyncMock(side_effect=[_embed_a, _embed_b]),
    )
    _, agent, headers = await _setup(client)

    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='['
                 '{"content": "Fact one", "importance": 0.8, "tags": ["a"]},'
                 '{"content": "Fact two", "importance": 0.6, "tags": ["b"]}'
                 ']'
        )
    ]
    mocker.patch(
        "crewlayer.core.memory.extractor._client.messages.create",
        new=AsyncMock(return_value=mock_response),
    )

    r = await client.post(
        f"/v1/agents/{agent['id']}/memory/extract",
        json={"conversation": "A multi-fact conversation."},
        headers=headers,
    )

    assert r.status_code == 200
    data = r.json()
    assert data["extracted_count"] == 2
    assert len(data["memory_ids"]) == 2


async def test_extract_handles_invalid_json_gracefully(client: AsyncClient, mocker) -> None:
    mocker.patch(
        "crewlayer.core.memory.long.get_embedding",
        new=AsyncMock(return_value=_FAKE_EMBEDDING),
    )
    _, agent, headers = await _setup(client)

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="This is not JSON at all.")]
    mocker.patch(
        "crewlayer.core.memory.extractor._client.messages.create",
        new=AsyncMock(return_value=mock_response),
    )

    r = await client.post(
        f"/v1/agents/{agent['id']}/memory/extract",
        json={"conversation": "Some text."},
        headers=headers,
    )

    assert r.status_code == 200
    assert r.json()["extracted_count"] == 0


# ---------------------------------------------------------------------------
# List memories
# ---------------------------------------------------------------------------

async def test_list_memories_paginated(client: AsyncClient, mocker) -> None:
    # Use three orthogonal unit vectors so no pair triggers the dedup merge path
    _e0 = [1.0] + [0.0] * 1535
    _e1 = [0.0, 1.0] + [0.0] * 1534
    _e2 = [0.0, 0.0, 1.0] + [0.0] * 1533
    mocker.patch(
        "crewlayer.core.memory.long.get_embedding",
        new=AsyncMock(side_effect=[_e0, _e1, _e2]),
    )
    _, agent, headers = await _setup(client)

    # Save 3 facts
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(
            text='['
                 '{"content": "A", "importance": 0.5, "tags": []},'
                 '{"content": "B", "importance": 0.5, "tags": []},'
                 '{"content": "C", "importance": 0.5, "tags": []}'
                 ']'
        )
    ]
    mocker.patch(
        "crewlayer.core.memory.extractor._client.messages.create",
        new=AsyncMock(return_value=mock_response),
    )
    await client.post(
        f"/v1/agents/{agent['id']}/memory/extract",
        json={"conversation": "abc"},
        headers=headers,
    )

    r = await client.get(
        f"/v1/agents/{agent['id']}/memory",
        headers=headers,
        params={"page": 1, "page_size": 2},
    )

    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 3
    assert len(data["items"]) == 2
    assert data["page"] == 1
    assert data["page_size"] == 2


# ---------------------------------------------------------------------------
# Delete (soft-delete)
# ---------------------------------------------------------------------------

async def test_delete_memory_removes_from_list(client: AsyncClient, mocker) -> None:
    mocker.patch(
        "crewlayer.core.memory.long.get_embedding",
        new=AsyncMock(return_value=_FAKE_EMBEDDING),
    )
    _, agent, headers = await _setup(client)

    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(text='[{"content": "To be deleted", "importance": 0.5, "tags": []}]')
    ]
    mocker.patch(
        "crewlayer.core.memory.extractor._client.messages.create",
        new=AsyncMock(return_value=mock_response),
    )
    extract_r = await client.post(
        f"/v1/agents/{agent['id']}/memory/extract",
        json={"conversation": "deleteme"},
        headers=headers,
    )
    memory_id = extract_r.json()["memory_ids"][0]

    # Delete it
    r = await client.delete(
        f"/v1/agents/{agent['id']}/memory/{memory_id}",
        headers=headers,
    )
    assert r.status_code == 204

    # Should no longer appear in list
    r = await client.get(f"/v1/agents/{agent['id']}/memory", headers=headers)
    assert r.status_code == 200
    ids = [item["id"] for item in r.json()["items"]]
    assert memory_id not in ids


async def test_delete_nonexistent_memory_returns_404(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)

    r = await client.delete(
        f"/v1/agents/{agent['id']}/memory/{uuid.uuid4()}",
        headers=headers,
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Cross-tenant isolation
# ---------------------------------------------------------------------------

async def test_recall_tenant_isolation(client: AsyncClient, mocker) -> None:
    """Tenant B cannot recall memories saved by tenant A."""
    mocker.patch(
        "crewlayer.core.memory.long.get_embedding",
        new=AsyncMock(return_value=_FAKE_EMBEDDING),
    )
    _, agent_a, headers_a = await _setup(client)
    _, agent_b, headers_b = await _setup(client)

    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(text='[{"content": "Tenant A secret", "importance": 1.0, "tags": []}]')
    ]
    mocker.patch(
        "crewlayer.core.memory.extractor._client.messages.create",
        new=AsyncMock(return_value=mock_response),
    )
    await client.post(
        f"/v1/agents/{agent_a['id']}/memory/extract",
        json={"conversation": "secret stuff"},
        headers=headers_a,
    )

    # Tenant B tries to recall from Tenant A's agent — should 404 (agent not visible)
    r = await client.post(
        f"/v1/agents/{agent_a['id']}/memory/recall",
        json={"query": "secret"},
        headers=headers_b,
    )
    assert r.status_code == 404
