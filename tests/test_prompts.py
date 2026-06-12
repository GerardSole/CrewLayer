"""Prompt version control tests: create, activate, rollback, diff, tenant isolation."""
import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _setup(client: AsyncClient) -> tuple[dict, dict, dict]:
    """Create a tenant + agent, return (tenant, agent, headers)."""
    r = await client.post("/v1/tenants", json={"name": f"PromptCo-{uuid.uuid4()}"})
    assert r.status_code == 201
    tenant = r.json()
    headers = {"X-API-Key": tenant["initial_api_key"]}

    r = await client.post("/v1/agents", json={"name": "prompt-agent"}, headers=headers)
    assert r.status_code == 201
    agent = r.json()

    return tenant, agent, headers


async def _create(client, agent_id, headers, content="Hello, agent.", description=None) -> dict:
    payload: dict = {"content": content}
    if description:
        payload["description"] = description
    r = await client.post(f"/v1/agents/{agent_id}/prompts", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

async def test_create_prompt_version_returns_201(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    r = await client.post(
        f"/v1/agents/{agent['id']}/prompts",
        json={"content": "You are a helpful assistant.", "description": "initial"},
        headers=headers,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["version"] == 1
    assert body["content"] == "You are a helpful assistant."
    assert body["description"] == "initial"
    assert body["is_active"] is False
    assert body["agent_id"] == agent["id"]


async def test_version_numbers_autoincrement(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    v1 = await _create(client, agent["id"], headers, "first")
    v2 = await _create(client, agent["id"], headers, "second")
    v3 = await _create(client, agent["id"], headers, "third")
    assert v1["version"] == 1
    assert v2["version"] == 2
    assert v3["version"] == 3


async def test_create_unknown_agent_returns_404(client: AsyncClient) -> None:
    _, _, headers = await _setup(client)
    r = await client.post(
        f"/v1/agents/{uuid.uuid4()}/prompts",
        json={"content": "test"},
        headers=headers,
    )
    assert r.status_code == 404


async def test_create_empty_content_returns_422(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    r = await client.post(
        f"/v1/agents/{agent['id']}/prompts",
        json={"content": ""},
        headers=headers,
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

async def test_list_returns_versions_newest_first(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    await _create(client, agent["id"], headers, "v1")
    await _create(client, agent["id"], headers, "v2")
    await _create(client, agent["id"], headers, "v3")

    r = await client.get(f"/v1/agents/{agent['id']}/prompts", headers=headers)
    assert r.status_code == 200
    body = r.json()
    versions = [item["version"] for item in body["items"]]
    assert versions == [3, 2, 1]
    assert body["count"] == 3


async def test_list_empty_agent_returns_empty(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    r = await client.get(f"/v1/agents/{agent['id']}/prompts", headers=headers)
    assert r.status_code == 200
    assert r.json() == {"items": [], "count": 0}


# ---------------------------------------------------------------------------
# Activate
# ---------------------------------------------------------------------------

async def test_activate_sets_is_active(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    pv = await _create(client, agent["id"], headers, "hello")

    r = await client.post(
        f"/v1/agents/{agent['id']}/prompts/{pv['id']}/activate",
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is True


async def test_only_one_active_at_a_time(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    v1 = await _create(client, agent["id"], headers, "v1")
    v2 = await _create(client, agent["id"], headers, "v2")

    # Activate v1
    await client.post(
        f"/v1/agents/{agent['id']}/prompts/{v1['id']}/activate", headers=headers
    )

    # Activate v2 — v1 must become inactive
    r = await client.post(
        f"/v1/agents/{agent['id']}/prompts/{v2['id']}/activate", headers=headers
    )
    assert r.status_code == 200

    page = await client.get(f"/v1/agents/{agent['id']}/prompts", headers=headers)
    items = page.json()["items"]
    active_ids = [i["id"] for i in items if i["is_active"]]
    assert len(active_ids) == 1
    assert active_ids[0] == v2["id"]


async def test_activate_unknown_version_returns_404(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    r = await client.post(
        f"/v1/agents/{agent['id']}/prompts/{uuid.uuid4()}/activate",
        headers=headers,
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# get_active
# ---------------------------------------------------------------------------

async def test_get_active_after_activate(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    pv = await _create(client, agent["id"], headers, "hello")
    await client.post(
        f"/v1/agents/{agent['id']}/prompts/{pv['id']}/activate", headers=headers
    )

    r = await client.get(f"/v1/agents/{agent['id']}/prompts/active", headers=headers)
    assert r.status_code == 200
    assert r.json()["id"] == pv["id"]


async def test_get_active_no_active_returns_404(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    await _create(client, agent["id"], headers, "hello")

    r = await client.get(f"/v1/agents/{agent['id']}/prompts/active", headers=headers)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------

async def test_rollback_activates_previous_version(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    v1 = await _create(client, agent["id"], headers, "v1")
    v2 = await _create(client, agent["id"], headers, "v2")

    # Activate v2
    await client.post(
        f"/v1/agents/{agent['id']}/prompts/{v2['id']}/activate", headers=headers
    )

    # Rollback → should activate v1
    r = await client.post(f"/v1/agents/{agent['id']}/prompts/rollback", headers=headers)
    assert r.status_code == 200
    assert r.json()["id"] == v1["id"]
    assert r.json()["is_active"] is True

    # v2 must now be inactive
    page = await client.get(f"/v1/agents/{agent['id']}/prompts", headers=headers)
    v2_item = next(i for i in page.json()["items"] if i["id"] == v2["id"])
    assert v2_item["is_active"] is False


async def test_rollback_with_no_active_returns_409(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    await _create(client, agent["id"], headers, "v1")

    r = await client.post(f"/v1/agents/{agent['id']}/prompts/rollback", headers=headers)
    assert r.status_code == 409


async def test_rollback_no_previous_version_returns_409(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    v1 = await _create(client, agent["id"], headers, "v1 only")
    await client.post(
        f"/v1/agents/{agent['id']}/prompts/{v1['id']}/activate", headers=headers
    )

    r = await client.post(f"/v1/agents/{agent['id']}/prompts/rollback", headers=headers)
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Get detail
# ---------------------------------------------------------------------------

async def test_get_version_detail(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    created = await _create(client, agent["id"], headers, "detailed content", "desc")

    r = await client.get(
        f"/v1/agents/{agent['id']}/prompts/{created['id']}", headers=headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == created["id"]
    assert body["content"] == "detailed content"
    assert body["description"] == "desc"


async def test_get_version_unknown_returns_404(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    r = await client.get(
        f"/v1/agents/{agent['id']}/prompts/{uuid.uuid4()}", headers=headers
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

async def test_diff_returns_changes(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    v1 = await _create(client, agent["id"], headers, "line one\nline two\nline three")
    v2 = await _create(
        client, agent["id"], headers, "line one\nline two modified\nline three\nline four"
    )

    r = await client.get(
        f"/v1/agents/{agent['id']}/prompts/diff",
        params={"a": v1["id"], "b": v2["id"]},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["version_id_a"] == v1["id"]
    assert body["version_id_b"] == v2["id"]

    ops = [line["operation"] for line in body["lines"]]
    assert "insert" in ops
    assert "delete" in ops


async def test_diff_identical_versions_all_equal(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    content = "same content\nno changes"
    v1 = await _create(client, agent["id"], headers, content)
    v2 = await _create(client, agent["id"], headers, content)

    r = await client.get(
        f"/v1/agents/{agent['id']}/prompts/diff",
        params={"a": v1["id"], "b": v2["id"]},
        headers=headers,
    )
    assert r.status_code == 200
    for line in r.json()["lines"]:
        assert line["operation"] == "equal"


async def test_diff_unknown_version_returns_404(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    v1 = await _create(client, agent["id"], headers, "hello")

    r = await client.get(
        f"/v1/agents/{agent['id']}/prompts/diff",
        params={"a": v1["id"], "b": str(uuid.uuid4())},
        headers=headers,
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------

async def test_tenant_isolation(client: AsyncClient) -> None:
    """Tenant A cannot read or activate tenant B's prompt versions."""
    _, agent_a, headers_a = await _setup(client)
    _, agent_b, headers_b = await _setup(client)

    pv_b = await _create(client, agent_b["id"], headers_b, "tenant B secret prompt")

    # Tenant A cannot read agent B's prompt
    r = await client.get(
        f"/v1/agents/{agent_b['id']}/prompts/{pv_b['id']}", headers=headers_a
    )
    assert r.status_code == 404

    # Tenant A cannot activate agent B's prompt
    r = await client.post(
        f"/v1/agents/{agent_b['id']}/prompts/{pv_b['id']}/activate", headers=headers_a
    )
    assert r.status_code == 404
