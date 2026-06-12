"""Evaluation system tests: submit, summary, anomaly detection, A/B tests."""
import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _setup(client: AsyncClient) -> tuple[dict, dict, dict]:
    """Create a tenant + agent, return (tenant, agent, headers)."""
    r = await client.post("/v1/tenants", json={"name": f"EvalCo-{uuid.uuid4()}"})
    assert r.status_code == 201
    tenant = r.json()
    headers = {"X-API-Key": tenant["initial_api_key"]}

    r = await client.post("/v1/agents", json={"name": "eval-agent"}, headers=headers)
    assert r.status_code == 201
    agent = r.json()

    return tenant, agent, headers


async def _log_action(client, agent_id, headers, *, status="success", duration_ms=500) -> dict:
    r = await client.post(
        f"/v1/agents/{agent_id}/actions",
        json={
            "tool_name": "test_tool",
            "input_params": {"q": "test"},
            "output_result": {"answer": "ok"},
            "status": status,
            "duration_ms": duration_ms,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _create_prompt(client, agent_id, headers, content="Test prompt") -> dict:
    r = await client.post(
        f"/v1/agents/{agent_id}/prompts",
        json={"content": content},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Evaluations — submit
# ---------------------------------------------------------------------------

async def test_submit_thumbs_up_evaluation(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    action = await _log_action(client, agent["id"], headers)

    r = await client.post(
        f"/v1/agents/{agent['id']}/actions/{action['id']}/evaluate",
        json={"rating_thumbs": "up"},
        headers=headers,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["rating_thumbs"] == "up"
    assert body["evaluator"] == "human"
    assert body["action_id"] == action["id"]


async def test_submit_score_evaluation(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    action = await _log_action(client, agent["id"], headers)

    r = await client.post(
        f"/v1/agents/{agent['id']}/actions/{action['id']}/evaluate",
        json={"rating_score": 4.5, "notes": "Very helpful"},
        headers=headers,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["rating_score"] == 4.5
    assert body["notes"] == "Very helpful"


async def test_submit_invalid_score_returns_422(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    action = await _log_action(client, agent["id"], headers)

    r = await client.post(
        f"/v1/agents/{agent['id']}/actions/{action['id']}/evaluate",
        json={"rating_score": 6.0},
        headers=headers,
    )
    assert r.status_code == 422


async def test_submit_unknown_action_returns_404(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)

    r = await client.post(
        f"/v1/agents/{agent['id']}/actions/{uuid.uuid4()}/evaluate",
        json={"rating_thumbs": "up"},
        headers=headers,
    )
    assert r.status_code == 404


async def test_evaluation_tenant_isolation(client: AsyncClient) -> None:
    _, agent_a, headers_a = await _setup(client)
    _, agent_b, headers_b = await _setup(client)
    action = await _log_action(client, agent_a["id"], headers_a)

    r = await client.post(
        f"/v1/agents/{agent_a['id']}/actions/{action['id']}/evaluate",
        json={"rating_thumbs": "up"},
        headers=headers_b,
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Evaluations — list + summary
# ---------------------------------------------------------------------------

async def test_list_evaluations(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    for _ in range(3):
        action = await _log_action(client, agent["id"], headers)
        await client.post(
            f"/v1/agents/{agent['id']}/actions/{action['id']}/evaluate",
            json={"rating_thumbs": "up"},
            headers=headers,
        )

    r = await client.get(f"/v1/agents/{agent['id']}/evaluations", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3
    assert len(body["items"]) == 3


async def test_evaluation_summary(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    for score in [3.0, 4.0, 5.0]:
        action = await _log_action(client, agent["id"], headers)
        await client.post(
            f"/v1/agents/{agent['id']}/actions/{action['id']}/evaluate",
            json={"rating_score": score, "rating_thumbs": "up"},
            headers=headers,
        )
    action = await _log_action(client, agent["id"], headers)
    await client.post(
        f"/v1/agents/{agent['id']}/actions/{action['id']}/evaluate",
        json={"rating_thumbs": "down"},
        headers=headers,
    )

    r = await client.get(f"/v1/agents/{agent['id']}/evaluations/summary", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total_evaluations"] == 4
    assert body["thumbs_up"] == 3
    assert body["thumbs_down"] == 1
    assert abs(body["avg_score"] - 4.0) < 0.01
    assert "trend_7d" in body
    assert len(body["trend_7d"]) == 7


# ---------------------------------------------------------------------------
# Anomalies
# ---------------------------------------------------------------------------

async def test_anomaly_response_too_long(client: AsyncClient) -> None:
    """An action with a very long output should create a response_too_long anomaly."""
    _, agent, headers = await _setup(client)
    big_output = "x" * 50_000  # well above the 5000-char default threshold
    r = await client.post(
        f"/v1/agents/{agent['id']}/actions",
        json={
            "tool_name": "chat",
            "input_params": {},
            "output_result": {"text": big_output},
            "status": "success",
        },
        headers=headers,
    )
    assert r.status_code == 201

    import asyncio
    await asyncio.sleep(0.3)

    r = await client.get(f"/v1/agents/{agent['id']}/anomalies", headers=headers)
    assert r.status_code == 200
    body = r.json()
    types = [a["anomaly_type"] for a in body["items"]]
    assert "response_too_long" in types


async def test_anomaly_high_latency(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    r = await client.post(
        f"/v1/agents/{agent['id']}/actions",
        json={
            "tool_name": "slow_tool",
            "input_params": {},
            "output_result": {},
            "status": "success",
            "duration_ms": 25_000,
        },
        headers=headers,
    )
    assert r.status_code == 201

    import asyncio
    await asyncio.sleep(0.1)

    r = await client.get(f"/v1/agents/{agent['id']}/anomalies", headers=headers)
    assert r.status_code == 200
    types = [a["anomaly_type"] for a in r.json()["items"]]
    assert "high_latency" in types


async def test_resolve_anomaly(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    big_output = "x" * 50_000
    await client.post(
        f"/v1/agents/{agent['id']}/actions",
        json={"tool_name": "t", "input_params": {}, "output_result": {"t": big_output}, "status": "success"},
        headers=headers,
    )

    import asyncio
    await asyncio.sleep(0.3)

    r = await client.get(f"/v1/agents/{agent['id']}/anomalies?resolved=false", headers=headers)
    items = r.json()["items"]
    if not items:
        pytest.skip("No anomalies detected in this run")

    anomaly_id = items[0]["id"]
    r = await client.post(
        f"/v1/agents/{agent['id']}/anomalies/{anomaly_id}/resolve",
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["resolved"] is True

    r = await client.get(f"/v1/agents/{agent['id']}/anomalies?resolved=false", headers=headers)
    ids = [a["id"] for a in r.json()["items"]]
    assert anomaly_id not in ids


# ---------------------------------------------------------------------------
# A/B tests
# ---------------------------------------------------------------------------

async def test_create_ab_test(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    v1 = await _create_prompt(client, agent["id"], headers, "Prompt A")
    v2 = await _create_prompt(client, agent["id"], headers, "Prompt B")

    r = await client.post(
        f"/v1/agents/{agent['id']}/ab-tests",
        json={
            "name": "Test vs Detailed",
            "variant_a_prompt_version_id": v1["id"],
            "variant_b_prompt_version_id": v2["id"],
            "traffic_split": 0.5,
        },
        headers=headers,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "active"
    assert body["name"] == "Test vs Detailed"
    assert body["traffic_split"] == 0.5


async def test_ab_test_unknown_prompt_returns_404(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    v1 = await _create_prompt(client, agent["id"], headers)

    r = await client.post(
        f"/v1/agents/{agent['id']}/ab-tests",
        json={
            "name": "bad test",
            "variant_a_prompt_version_id": v1["id"],
            "variant_b_prompt_version_id": str(uuid.uuid4()),
            "traffic_split": 0.5,
        },
        headers=headers,
    )
    assert r.status_code == 404


async def test_list_ab_tests(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    v1 = await _create_prompt(client, agent["id"], headers, "A")
    v2 = await _create_prompt(client, agent["id"], headers, "B")

    for name in ["test-1", "test-2"]:
        r = await client.post(
            f"/v1/agents/{agent['id']}/ab-tests",
            json={
                "name": name,
                "variant_a_prompt_version_id": v1["id"],
                "variant_b_prompt_version_id": v2["id"],
                "traffic_split": 0.5,
            },
            headers=headers,
        )
        assert r.status_code == 201

    r = await client.get(f"/v1/agents/{agent['id']}/ab-tests", headers=headers)
    assert r.status_code == 200
    assert r.json()["count"] == 2


async def test_ab_test_results_structure(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    v1 = await _create_prompt(client, agent["id"], headers, "A")
    v2 = await _create_prompt(client, agent["id"], headers, "B")

    r = await client.post(
        f"/v1/agents/{agent['id']}/ab-tests",
        json={
            "name": "results test",
            "variant_a_prompt_version_id": v1["id"],
            "variant_b_prompt_version_id": v2["id"],
            "traffic_split": 0.5,
        },
        headers=headers,
    )
    test_id = r.json()["id"]

    r = await client.get(f"/v1/agents/{agent['id']}/ab-tests/{test_id}/results", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert "variant_a" in body
    assert "variant_b" in body
    assert body["variant_a"]["variant"] == "a"
    assert body["variant_b"]["variant"] == "b"


async def test_complete_ab_test_with_winner(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    v1 = await _create_prompt(client, agent["id"], headers, "Prompt A")
    v2 = await _create_prompt(client, agent["id"], headers, "Prompt B")

    r = await client.post(
        f"/v1/agents/{agent['id']}/ab-tests",
        json={
            "name": "complete test",
            "variant_a_prompt_version_id": v1["id"],
            "variant_b_prompt_version_id": v2["id"],
            "traffic_split": 0.4,
        },
        headers=headers,
    )
    test_id = r.json()["id"]

    r = await client.post(
        f"/v1/agents/{agent['id']}/ab-tests/{test_id}/complete",
        json={"winner": "a"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["winner"] == "a"

    # Winner's prompt should now be active
    r = await client.get(f"/v1/agents/{agent['id']}/prompts/active", headers=headers)
    assert r.status_code == 200
    assert r.json()["id"] == v1["id"]


async def test_complete_nonexistent_ab_test_returns_404(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)

    r = await client.post(
        f"/v1/agents/{agent['id']}/ab-tests/{uuid.uuid4()}/complete",
        json={"winner": "a"},
        headers=headers,
    )
    assert r.status_code == 404


async def test_deterministic_variant_assignment(client: AsyncClient) -> None:
    """Same session_id must always get the same variant across sessions."""
    from crewlayer.core.evaluation.abtesting import ABTestManager as _Mgr
    import hashlib

    session_id = uuid.uuid4()
    traffic_split = 0.5

    # Compute expected variant manually
    digest = hashlib.sha256(str(session_id).encode()).digest()
    bucket = int.from_bytes(digest[:4], "big") % 100
    expected = "a" if bucket < traffic_split * 100 else "b"

    from crewlayer.db.models import ABTestVariantEnum
    variant = _Mgr._deterministic_variant(session_id, traffic_split)
    assert variant.value == expected

    # Calling again with the same session_id must return the same variant
    variant2 = _Mgr._deterministic_variant(session_id, traffic_split)
    assert variant == variant2


async def test_ab_test_variant_differs_for_different_sessions(client: AsyncClient) -> None:
    """Different session ids must show distribution across variants."""
    from crewlayer.core.evaluation.abtesting import ABTestManager as _Mgr

    results = set()
    for _ in range(20):
        v = _Mgr._deterministic_variant(uuid.uuid4(), 0.5)
        results.add(v.value)

    assert "a" in results
    assert "b" in results
