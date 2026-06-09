"""Action logger tests: logging, retrieval, filtering, stats, tenant isolation."""
import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _setup(client: AsyncClient) -> tuple[dict, dict, dict]:
    """Create a tenant + agent, return (tenant, agent, headers)."""
    r = await client.post("/v1/tenants", json={"name": f"ActCo-{uuid.uuid4()}"})
    assert r.status_code == 201
    tenant = r.json()
    headers = {"X-API-Key": tenant["initial_api_key"]}

    r = await client.post("/v1/agents", json={"name": "action-agent"}, headers=headers)
    assert r.status_code == 201
    agent = r.json()

    return tenant, agent, headers


_ACTION_PAYLOAD = {
    "tool_name": "send_email",
    "input_params": {"to": "test@example.com"},
    "output_result": {"message_id": "abc123"},
    "status": "success",
    "duration_ms": 150,
}


async def _log(client, agent_id, headers, **overrides) -> dict:
    payload = {**_ACTION_PAYLOAD, **overrides}
    r = await client.post(f"/v1/agents/{agent_id}/actions", json=payload, headers=headers)
    assert r.status_code == 201
    return r.json()


# ---------------------------------------------------------------------------
# Log and retrieve
# ---------------------------------------------------------------------------

async def test_log_action_returns_immutable_record(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)

    r = await client.post(
        f"/v1/agents/{agent['id']}/actions",
        json={
            "tool_name": "web_search",
            "input_params": {"query": "FastAPI"},
            "output_result": {"results": ["fastapi.tiangolo.com"]},
            "status": "success",
            "duration_ms": 320,
            "metadata": {"source": "test"},
        },
        headers=headers,
    )

    assert r.status_code == 201
    data = r.json()
    assert data["tool_name"] == "web_search"
    assert data["status"] == "success"
    assert data["duration_ms"] == 320
    assert data["metadata"]["source"] == "test"
    assert "id" in data
    assert "timestamp" in data


async def test_get_action_by_id(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    action = await _log(client, agent["id"], headers)

    r = await client.get(f"/v1/agents/{agent['id']}/actions/{action['id']}", headers=headers)

    assert r.status_code == 200
    assert r.json()["id"] == action["id"]
    assert r.json()["tool_name"] == action["tool_name"]


async def test_get_nonexistent_action_returns_404(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)

    r = await client.get(f"/v1/agents/{agent['id']}/actions/{uuid.uuid4()}", headers=headers)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# List with filters
# ---------------------------------------------------------------------------

async def test_list_actions_returns_all(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)

    for _ in range(3):
        await _log(client, agent["id"], headers)

    r = await client.get(f"/v1/agents/{agent['id']}/actions", headers=headers)

    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 3
    assert len(data["items"]) == 3


async def test_filter_by_tool_name(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)

    await _log(client, agent["id"], headers, tool_name="send_email")
    await _log(client, agent["id"], headers, tool_name="web_search")
    await _log(client, agent["id"], headers, tool_name="send_email")

    r = await client.get(
        f"/v1/agents/{agent['id']}/actions",
        params={"tool": "send_email"},
        headers=headers,
    )

    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2
    assert all(item["tool_name"] == "send_email" for item in data["items"])


async def test_filter_by_status(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)

    await _log(client, agent["id"], headers, status="success")
    await _log(client, agent["id"], headers, status="error", error_msg="boom")
    await _log(client, agent["id"], headers, status="error", error_msg="boom2")

    r = await client.get(
        f"/v1/agents/{agent['id']}/actions",
        params={"status": "error"},
        headers=headers,
    )

    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2
    assert all(item["status"] == "error" for item in data["items"])


async def test_list_returns_newest_first(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)

    first = await _log(client, agent["id"], headers, tool_name="first")
    await _log(client, agent["id"], headers, tool_name="second")
    third = await _log(client, agent["id"], headers, tool_name="third")

    r = await client.get(f"/v1/agents/{agent['id']}/actions", headers=headers)
    items = r.json()["items"]

    # DESC order: third, second, first
    assert items[0]["id"] == third["id"]
    assert items[-1]["id"] == first["id"]


async def test_cursor_pagination(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)

    # Log 5 actions
    for i in range(5):
        await _log(client, agent["id"], headers, tool_name=f"tool_{i}")

    # First page: 3 items
    r = await client.get(
        f"/v1/agents/{agent['id']}/actions",
        params={"limit": 3},
        headers=headers,
    )
    assert r.status_code == 200
    page1 = r.json()
    assert page1["count"] == 3
    assert page1["next_cursor"] is not None

    # Second page using cursor
    r = await client.get(
        f"/v1/agents/{agent['id']}/actions",
        params={"limit": 3, "cursor": page1["next_cursor"]},
        headers=headers,
    )
    assert r.status_code == 200
    page2 = r.json()
    assert page2["count"] == 2
    assert page2["next_cursor"] is None  # no more pages

    # No overlap between pages
    ids_1 = {item["id"] for item in page1["items"]}
    ids_2 = {item["id"] for item in page2["items"]}
    assert ids_1.isdisjoint(ids_2)
    assert len(ids_1 | ids_2) == 5


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

async def test_stats_totals_and_error_rate(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)

    await _log(client, agent["id"], headers, status="success", duration_ms=100, tool_name="t1")
    await _log(client, agent["id"], headers, status="success", duration_ms=200, tool_name="t1")
    await _log(client, agent["id"], headers, status="error", duration_ms=50, tool_name="t2", error_msg="x")

    r = await client.get(f"/v1/agents/{agent['id']}/actions/stats", headers=headers)

    assert r.status_code == 200
    data = r.json()
    assert data["total_actions"] == 3
    assert abs(data["error_rate"] - 1 / 3) < 0.001
    assert data["avg_duration_ms"] == pytest.approx((100 + 200 + 50) / 3, rel=0.01)

    by_tool = {t["tool_name"]: t for t in data["by_tool"]}
    assert by_tool["t1"]["count"] == 2
    assert by_tool["t1"]["error_rate"] == 0.0
    assert by_tool["t2"]["count"] == 1
    assert by_tool["t2"]["error_rate"] == pytest.approx(1.0)


async def test_stats_empty_agent(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)

    r = await client.get(f"/v1/agents/{agent['id']}/actions/stats", headers=headers)

    assert r.status_code == 200
    data = r.json()
    assert data["total_actions"] == 0
    assert data["error_rate"] == 0.0
    assert data["by_tool"] == []


# ---------------------------------------------------------------------------
# Cross-tenant isolation
# ---------------------------------------------------------------------------

async def test_tenant_cannot_list_foreign_agent_actions(client: AsyncClient) -> None:
    _, agent_a, headers_a = await _setup(client)
    _, _, headers_b = await _setup(client)

    await _log(client, agent_a["id"], headers_a)

    # Tenant B tries to list Tenant A's agent's actions
    r = await client.get(f"/v1/agents/{agent_a['id']}/actions", headers=headers_b)
    assert r.status_code == 404


async def test_tenant_cannot_get_foreign_action(client: AsyncClient) -> None:
    _, agent_a, headers_a = await _setup(client)
    _, _, headers_b = await _setup(client)

    action = await _log(client, agent_a["id"], headers_a)

    r = await client.get(f"/v1/agents/{agent_a['id']}/actions/{action['id']}", headers=headers_b)
    assert r.status_code == 404


async def test_tenant_cannot_get_foreign_stats(client: AsyncClient) -> None:
    _, agent_a, headers_a = await _setup(client)
    _, _, headers_b = await _setup(client)

    r = await client.get(f"/v1/agents/{agent_a['id']}/actions/stats", headers=headers_b)
    assert r.status_code == 404
