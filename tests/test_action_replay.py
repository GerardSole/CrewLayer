"""Tests for the action-replay feature.

Non-streaming tests use ``client`` (REST setup) + ``db`` for direct inserts.
Streaming tests use ``streaming_client`` (fresh session per request).
Timing tests combine ``streaming_client`` + ``db`` to control action timestamps.
"""
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import crewlayer.core.actions.replay as replay_mod
from crewlayer.db.models import Action, ActionStatus, Replay

# ─── helpers ─────────────────────────────────────────────────────────────────

async def _setup(client: AsyncClient) -> tuple[dict, dict, dict]:
    """Create tenant + agent via REST, return (tenant, agent, headers)."""
    r = await client.post("/v1/tenants", json={"name": f"replay-tenant-{uuid.uuid4()}"})
    assert r.status_code == 201
    tenant = r.json()
    headers = {"X-API-Key": tenant["initial_api_key"]}
    r = await client.post("/v1/agents", json={"name": "replay-agent"}, headers=headers)
    assert r.status_code == 201
    return tenant, r.json(), headers


async def _collect_sse(resp: Any) -> list[dict[str, Any]]:
    """Parse SSE lines into [{type, data}] dicts."""
    events: list[dict[str, Any]] = []
    current_type: str | None = None
    async for line in resp.aiter_lines():
        stripped = line.strip()
        if stripped.startswith("event:"):
            current_type = stripped[6:].strip()
        elif stripped.startswith("data:"):
            data_str = stripped[5:].strip()
            if data_str:
                try:
                    data = json.loads(data_str)
                    events.append({"type": current_type or "message", "data": data})
                except json.JSONDecodeError:
                    pass
                current_type = None
    return events


# ─── create replay ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_replay_returns_201(client: AsyncClient) -> None:
    tenant, agent, hdrs = await _setup(client)
    now = datetime.now(UTC)
    body = {
        "from_timestamp": (now - timedelta(hours=1)).isoformat(),
        "to_timestamp": now.isoformat(),
        "speed": 2.0,
    }
    resp = await client.post(f"/v1/agents/{agent['id']}/replays", json=body, headers=hdrs)
    assert resp.status_code == 201
    data = resp.json()
    assert data["agent_id"] == agent["id"]
    assert data["status"] == "pending"
    assert data["speed"] == 2.0
    assert data["action_count"] == 0
    assert data["started_at"] is None
    assert data["completed_at"] is None


@pytest.mark.asyncio
async def test_create_replay_counts_actions_in_range(client: AsyncClient, db: AsyncSession) -> None:
    tenant, agent, hdrs = await _setup(client)
    now = datetime.now(UTC)
    t = [now - timedelta(minutes=x) for x in range(6, 0, -1)]  # oldest first

    tenant_id = uuid.UUID(tenant["id"])
    agent_id = uuid.UUID(agent["id"])
    for ts in t:
        db.add(Action(
            tenant_id=tenant_id, agent_id=agent_id,
            tool_name="tool", input_params={}, output_result={},
            status=ActionStatus.success, timestamp=ts,
        ))
    await db.commit()

    # Range t[1]..t[3] → 3 actions
    body = {
        "from_timestamp": t[1].isoformat(),
        "to_timestamp": t[3].isoformat(),
    }
    resp = await client.post(f"/v1/agents/{agent['id']}/replays", json=body, headers=hdrs)
    assert resp.status_code == 201
    assert resp.json()["action_count"] == 3


@pytest.mark.asyncio
async def test_create_replay_invalid_range_returns_422(client: AsyncClient) -> None:
    _, agent, hdrs = await _setup(client)
    now = datetime.now(UTC)
    body = {
        "from_timestamp": now.isoformat(),
        "to_timestamp": (now - timedelta(hours=1)).isoformat(),
    }
    resp = await client.post(f"/v1/agents/{agent['id']}/replays", json=body, headers=hdrs)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_replay_unknown_agent_returns_404(client: AsyncClient) -> None:
    tenant_resp = await client.post("/v1/tenants", json={"name": "t404"})
    hdrs = {"X-API-Key": tenant_resp.json()["initial_api_key"]}
    now = datetime.now(UTC)
    resp = await client.post(
        f"/v1/agents/{uuid.uuid4()}/replays",
        json={"from_timestamp": (now - timedelta(hours=1)).isoformat(), "to_timestamp": now.isoformat()},
        headers=hdrs,
    )
    assert resp.status_code == 404


# ─── list replays ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_replays_returns_all(client: AsyncClient) -> None:
    _, agent, hdrs = await _setup(client)
    now = datetime.now(UTC)
    for _ in range(3):
        await client.post(
            f"/v1/agents/{agent['id']}/replays",
            json={"from_timestamp": (now - timedelta(hours=1)).isoformat(), "to_timestamp": now.isoformat()},
            headers=hdrs,
        )
    resp = await client.get(f"/v1/agents/{agent['id']}/replays", headers=hdrs)
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 3
    assert len(body["items"]) == 3


@pytest.mark.asyncio
async def test_list_replays_empty_for_new_agent(client: AsyncClient) -> None:
    _, agent, hdrs = await _setup(client)
    resp = await client.get(f"/v1/agents/{agent['id']}/replays", headers=hdrs)
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


# ─── get replay detail ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_replay_returns_detail(client: AsyncClient) -> None:
    _, agent, hdrs = await _setup(client)
    now = datetime.now(UTC)
    create_resp = await client.post(
        f"/v1/agents/{agent['id']}/replays",
        json={"from_timestamp": (now - timedelta(hours=1)).isoformat(), "to_timestamp": now.isoformat(), "speed": 5.0},
        headers=hdrs,
    )
    assert create_resp.status_code == 201
    rid = create_resp.json()["id"]

    resp = await client.get(f"/v1/agents/{agent['id']}/replays/{rid}", headers=hdrs)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == rid
    assert data["speed"] == 5.0
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_get_replay_not_found_returns_404(client: AsyncClient) -> None:
    _, agent, hdrs = await _setup(client)
    resp = await client.get(f"/v1/agents/{agent['id']}/replays/{uuid.uuid4()}", headers=hdrs)
    assert resp.status_code == 404


# ─── tenant isolation ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tenant_isolation_cannot_access_other_tenant_replay(client: AsyncClient) -> None:
    # Tenant A creates a replay
    tenant_a, agent_a, hdrs_a = await _setup(client)
    now = datetime.now(UTC)
    r = await client.post(
        f"/v1/agents/{agent_a['id']}/replays",
        json={"from_timestamp": (now - timedelta(hours=1)).isoformat(), "to_timestamp": now.isoformat()},
        headers=hdrs_a,
    )
    rid = r.json()["id"]

    # Tenant B tries to access tenant A's replay
    r_b = await client.post("/v1/tenants", json={"name": "tenant-b"})
    hdrs_b = {"X-API-Key": r_b.json()["initial_api_key"]}
    await client.post("/v1/agents", json={"name": "b-agent"}, headers=hdrs_b)

    # B cannot GET from A's agent
    resp = await client.get(f"/v1/agents/{agent_a['id']}/replays/{rid}", headers=hdrs_b)
    assert resp.status_code in (403, 404)

    # B also cannot list under A's agent
    resp2 = await client.get(f"/v1/agents/{agent_a['id']}/replays", headers=hdrs_b)
    assert resp2.status_code in (403, 404)


# ─── SSE stream tests ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_emits_actions_in_order(streaming_client: AsyncClient) -> None:
    """Stream emits action events in chronological order, then completed."""
    tenant, agent, hdrs = await _setup(streaming_client)
    t0 = datetime.now(UTC)
    for tool in ("alpha", "beta", "gamma"):
        r = await streaming_client.post(
            f"/v1/agents/{agent['id']}/actions",
            json={"tool_name": tool, "input_params": {}, "output_result": {}, "status": "success"},
            headers=hdrs,
        )
        assert r.status_code == 201
    t1 = datetime.now(UTC)

    rr = await streaming_client.post(
        f"/v1/agents/{agent['id']}/replays",
        json={"from_timestamp": t0.isoformat(), "to_timestamp": t1.isoformat(), "speed": 1000.0},
        headers=hdrs,
    )
    assert rr.status_code == 201
    assert rr.json()["action_count"] == 3
    rid = rr.json()["id"]

    async with streaming_client.stream(
        "GET", f"/v1/agents/{agent['id']}/replays/{rid}/stream", headers=hdrs
    ) as resp:
        assert resp.status_code == 200
        events = await _collect_sse(resp)

    action_events = [e for e in events if e["type"] == "action"]
    completed_events = [e for e in events if e["type"] == "completed"]

    assert len(action_events) == 3
    assert len(completed_events) == 1
    assert [e["data"]["index"] for e in action_events] == [0, 1, 2]
    assert all(e["data"]["total"] == 3 for e in action_events)


@pytest.mark.asyncio
async def test_stream_updates_replay_status_to_completed(streaming_client: AsyncClient) -> None:
    """After full stream, replay transitions to completed with timestamps set."""
    tenant, agent, hdrs = await _setup(streaming_client)
    t0 = datetime.now(UTC)
    await streaming_client.post(
        f"/v1/agents/{agent['id']}/actions",
        json={"tool_name": "t", "input_params": {}, "output_result": {}, "status": "success"},
        headers=hdrs,
    )
    t1 = datetime.now(UTC)

    rr = await streaming_client.post(
        f"/v1/agents/{agent['id']}/replays",
        json={"from_timestamp": t0.isoformat(), "to_timestamp": t1.isoformat(), "speed": 1000.0},
        headers=hdrs,
    )
    rid = rr.json()["id"]

    async with streaming_client.stream(
        "GET", f"/v1/agents/{agent['id']}/replays/{rid}/stream", headers=hdrs
    ) as resp:
        await _collect_sse(resp)

    detail = await streaming_client.get(f"/v1/agents/{agent['id']}/replays/{rid}", headers=hdrs)
    assert detail.json()["status"] == "completed"
    assert detail.json()["completed_at"] is not None
    assert detail.json()["started_at"] is not None


@pytest.mark.asyncio
async def test_stream_empty_replay_completes_immediately(streaming_client: AsyncClient) -> None:
    """A replay with no actions emits only a completed event with action_count=0."""
    tenant, agent, hdrs = await _setup(streaming_client)
    past = datetime(2000, 1, 1, tzinfo=UTC)
    rr = await streaming_client.post(
        f"/v1/agents/{agent['id']}/replays",
        json={
            "from_timestamp": past.isoformat(),
            "to_timestamp": (past + timedelta(hours=1)).isoformat(),
            "speed": 1.0,
        },
        headers=hdrs,
    )
    assert rr.json()["action_count"] == 0
    rid = rr.json()["id"]

    async with streaming_client.stream(
        "GET", f"/v1/agents/{agent['id']}/replays/{rid}/stream", headers=hdrs
    ) as resp:
        events = await _collect_sse(resp)

    assert [e for e in events if e["type"] == "action"] == []
    completed = [e for e in events if e["type"] == "completed"]
    assert len(completed) == 1
    assert completed[0]["data"]["action_count"] == 0


@pytest.mark.asyncio
async def test_stream_can_be_replayed_after_completion(streaming_client: AsyncClient) -> None:
    """A completed replay can be re-streamed (re-runs from pending)."""
    tenant, agent, hdrs = await _setup(streaming_client)
    past = datetime(2000, 1, 1, tzinfo=UTC)
    rr = await streaming_client.post(
        f"/v1/agents/{agent['id']}/replays",
        json={"from_timestamp": past.isoformat(), "to_timestamp": (past + timedelta(hours=1)).isoformat()},
        headers=hdrs,
    )
    rid = rr.json()["id"]

    # First stream
    async with streaming_client.stream(
        "GET", f"/v1/agents/{agent['id']}/replays/{rid}/stream", headers=hdrs
    ) as resp:
        await _collect_sse(resp)

    # Second stream on completed replay — should succeed, not 409
    async with streaming_client.stream(
        "GET", f"/v1/agents/{agent['id']}/replays/{rid}/stream", headers=hdrs
    ) as resp2:
        events2 = await _collect_sse(resp2)

    assert any(e["type"] == "completed" for e in events2)


# ─── speed / timing ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_speed_affects_inter_action_delay(
    streaming_client: AsyncClient, db: AsyncSession
) -> None:
    """speed=2.0 with actions 10 s apart → asyncio.sleep called with 5.0 s."""
    # Create tenant/agent via REST
    tenant_resp = await streaming_client.post(
        "/v1/tenants", json={"name": f"timing-{uuid.uuid4()}"}
    )
    t = tenant_resp.json()
    hdrs = {"X-API-Key": t["initial_api_key"]}
    a_resp = await streaming_client.post("/v1/agents", json={"name": "timing-a"}, headers=hdrs)
    tenant_id = uuid.UUID(t["id"])
    agent_id = uuid.UUID(a_resp.json()["id"])

    # Insert 2 actions with controlled timestamps directly in db
    t0 = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    t1 = t0 + timedelta(seconds=10)
    db.add(Action(
        tenant_id=tenant_id, agent_id=agent_id,
        tool_name="first", input_params={}, output_result={},
        status=ActionStatus.success, timestamp=t0,
    ))
    db.add(Action(
        tenant_id=tenant_id, agent_id=agent_id,
        tool_name="second", input_params={}, output_result={},
        status=ActionStatus.success, timestamp=t1,
    ))
    replay = Replay(
        tenant_id=tenant_id, agent_id=agent_id,
        from_timestamp=t0 - timedelta(seconds=1),
        to_timestamp=t1 + timedelta(seconds=1),
        speed=2.0, action_count=2,
    )
    db.add(replay)
    await db.commit()

    sleep_mock = AsyncMock()
    with patch.object(replay_mod.asyncio, "sleep", sleep_mock):
        async with streaming_client.stream(
            "GET", f"/v1/agents/{agent_id}/replays/{replay.id}/stream", headers=hdrs
        ) as resp:
            await _collect_sse(resp)

    # delta=10s, speed=2.0 → sleep(5.0)
    assert sleep_mock.call_count == 1
    assert abs(sleep_mock.call_args_list[0][0][0] - 5.0) < 0.01


@pytest.mark.asyncio
async def test_speed_1x_uses_original_delta(
    streaming_client: AsyncClient, db: AsyncSession
) -> None:
    """speed=1.0 preserves the original inter-action gap exactly."""
    tenant_resp = await streaming_client.post(
        "/v1/tenants", json={"name": f"speed1-{uuid.uuid4()}"}
    )
    t = tenant_resp.json()
    hdrs = {"X-API-Key": t["initial_api_key"]}
    a_resp = await streaming_client.post("/v1/agents", json={"name": "speed1-a"}, headers=hdrs)
    tenant_id = uuid.UUID(t["id"])
    agent_id = uuid.UUID(a_resp.json()["id"])

    t0 = datetime(2025, 6, 1, tzinfo=UTC)
    t1 = t0 + timedelta(seconds=7)
    db.add(Action(
        tenant_id=tenant_id, agent_id=agent_id,
        tool_name="a", input_params={}, output_result={},
        status=ActionStatus.success, timestamp=t0,
    ))
    db.add(Action(
        tenant_id=tenant_id, agent_id=agent_id,
        tool_name="b", input_params={}, output_result={},
        status=ActionStatus.success, timestamp=t1,
    ))
    replay = Replay(
        tenant_id=tenant_id, agent_id=agent_id,
        from_timestamp=t0 - timedelta(seconds=1),
        to_timestamp=t1 + timedelta(seconds=1),
        speed=1.0, action_count=2,
    )
    db.add(replay)
    await db.commit()

    sleep_mock = AsyncMock()
    with patch.object(replay_mod.asyncio, "sleep", sleep_mock):
        async with streaming_client.stream(
            "GET", f"/v1/agents/{agent_id}/replays/{replay.id}/stream", headers=hdrs
        ) as resp:
            await _collect_sse(resp)

    assert sleep_mock.call_count == 1
    assert abs(sleep_mock.call_args_list[0][0][0] - 7.0) < 0.01
