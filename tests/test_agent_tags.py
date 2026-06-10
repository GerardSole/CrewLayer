"""Tests for agent tag support: create with tags, filter, list unique tags, add/remove."""
import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _setup(client: AsyncClient) -> tuple[dict, dict]:
    r = await client.post("/v1/tenants", json={"name": f"TagCo-{uuid.uuid4()}"})
    assert r.status_code == 201
    tenant = r.json()
    return tenant, {"X-API-Key": tenant["initial_api_key"]}


async def _create_agent(client: AsyncClient, headers: dict, name: str, tags: list[str] | None = None) -> dict:
    body: dict = {"name": name, "description": "test"}
    if tags is not None:
        body["tags"] = tags
    r = await client.post("/v1/agents", json=body, headers=headers)
    assert r.status_code == 201
    return r.json()


# ---------------------------------------------------------------------------
# Create with tags
# ---------------------------------------------------------------------------

async def test_create_agent_with_tags(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers, "bot-1", tags=["prod", "ventas"])
    assert sorted(agent["tags"]) == ["prod", "ventas"]


async def test_create_agent_without_tags_defaults_empty(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers, "bot-2")
    assert agent["tags"] == []


async def test_create_agent_deduplicates_tags(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers, "bot-dup", tags=["x", "x", "y"])
    assert sorted(agent["tags"]) == ["x", "y"]


# ---------------------------------------------------------------------------
# GET /v1/agents filter by tags
# ---------------------------------------------------------------------------

async def test_filter_by_single_tag(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    await _create_agent(client, headers, "a", tags=["prod"])
    await _create_agent(client, headers, "b", tags=["dev"])
    await _create_agent(client, headers, "c", tags=["prod", "dev"])

    r = await client.get("/v1/agents?tags=prod", headers=headers)
    assert r.status_code == 200
    names = {a["name"] for a in r.json()}
    assert names == {"a", "c"}


async def test_filter_by_multiple_tags_and_logic(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    await _create_agent(client, headers, "a", tags=["prod"])
    await _create_agent(client, headers, "b", tags=["prod", "ventas"])
    await _create_agent(client, headers, "c", tags=["prod", "ventas", "interno"])

    r = await client.get("/v1/agents?tags=prod,ventas", headers=headers)
    assert r.status_code == 200
    names = {a["name"] for a in r.json()}
    assert names == {"b", "c"}


async def test_filter_by_tag_returns_empty_when_no_match(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    await _create_agent(client, headers, "a", tags=["prod"])

    r = await client.get("/v1/agents?tags=nonexistent", headers=headers)
    assert r.status_code == 200
    assert r.json() == []


async def test_filter_tags_combined_with_status(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    await _create_agent(client, headers, "a", tags=["prod"])
    await _create_agent(client, headers, "b", tags=["prod"])

    r = await client.get("/v1/agents?tags=prod&status=idle", headers=headers)
    assert r.status_code == 200
    assert len(r.json()) == 2


# ---------------------------------------------------------------------------
# GET /v1/agents/tags — unique tags with counts
# ---------------------------------------------------------------------------

async def test_list_tags_empty_when_no_agents(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    r = await client.get("/v1/agents/tags", headers=headers)
    assert r.status_code == 200
    assert r.json() == []


async def test_list_tags_counts_correctly(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    await _create_agent(client, headers, "a", tags=["prod", "ventas"])
    await _create_agent(client, headers, "b", tags=["prod"])
    await _create_agent(client, headers, "c", tags=["ventas"])

    r = await client.get("/v1/agents/tags", headers=headers)
    assert r.status_code == 200
    data = {item["tag"]: item["count"] for item in r.json()}
    assert data == {"prod": 2, "ventas": 2}


async def test_list_tags_tenant_isolation(client: AsyncClient) -> None:
    _, headers_a = await _setup(client)
    _, headers_b = await _setup(client)
    await _create_agent(client, headers_a, "a1", tags=["secret"])

    r = await client.get("/v1/agents/tags", headers=headers_b)
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# PATCH /v1/agents/{id} — update tags (and other fields)
# ---------------------------------------------------------------------------

async def test_patch_agent_replaces_tags(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers, "bot", tags=["old"])

    r = await client.patch(f"/v1/agents/{agent['id']}", json={"tags": ["new1", "new2"]}, headers=headers)
    assert r.status_code == 200
    assert sorted(r.json()["tags"]) == ["new1", "new2"]


async def test_patch_agent_clears_tags(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers, "bot", tags=["x"])

    r = await client.patch(f"/v1/agents/{agent['id']}", json={"tags": []}, headers=headers)
    assert r.status_code == 200
    assert r.json()["tags"] == []


async def test_patch_agent_updates_name_without_changing_tags(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers, "old-name", tags=["keep"])

    r = await client.patch(f"/v1/agents/{agent['id']}", json={"name": "new-name"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["name"] == "new-name"
    assert r.json()["tags"] == ["keep"]


# ---------------------------------------------------------------------------
# POST /v1/agents/{id}/tags — add tags without replacement
# ---------------------------------------------------------------------------

async def test_add_tags_appends_without_removing_existing(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers, "bot", tags=["existing"])

    r = await client.post(f"/v1/agents/{agent['id']}/tags", json={"tags": ["new1", "new2"]}, headers=headers)
    assert r.status_code == 200
    assert sorted(r.json()["tags"]) == ["existing", "new1", "new2"]


async def test_add_tags_ignores_duplicates(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers, "bot", tags=["x"])

    r = await client.post(f"/v1/agents/{agent['id']}/tags", json={"tags": ["x", "y"]}, headers=headers)
    assert r.status_code == 200
    assert sorted(r.json()["tags"]) == ["x", "y"]


async def test_add_tags_to_agent_without_tags(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers, "bot")

    r = await client.post(f"/v1/agents/{agent['id']}/tags", json={"tags": ["first"]}, headers=headers)
    assert r.status_code == 200
    assert r.json()["tags"] == ["first"]


# ---------------------------------------------------------------------------
# DELETE /v1/agents/{id}/tags/{tag} — remove single tag
# ---------------------------------------------------------------------------

async def test_remove_tag_removes_only_that_tag(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers, "bot", tags=["keep", "remove"])

    r = await client.delete(f"/v1/agents/{agent['id']}/tags/remove", headers=headers)
    assert r.status_code == 200
    assert r.json()["tags"] == ["keep"]


async def test_remove_tag_returns_404_if_not_present(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers, "bot", tags=["x"])

    r = await client.delete(f"/v1/agents/{agent['id']}/tags/nonexistent", headers=headers)
    assert r.status_code == 404


async def test_remove_last_tag_leaves_empty_list(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers, "bot", tags=["solo"])

    r = await client.delete(f"/v1/agents/{agent['id']}/tags/solo", headers=headers)
    assert r.status_code == 200
    assert r.json()["tags"] == []
