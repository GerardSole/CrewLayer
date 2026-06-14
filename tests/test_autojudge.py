"""Tests for LLM-as-a-judge auto-evaluation endpoints."""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MOCK_CRITERIA_SCORES = {
    "correctness": 4.5,
    "efficiency": 5.0,
    "completeness": 4.0,
    "safety": 5.0,
}
_MOCK_SCORE = 4.625
_MOCK_REASONING = "The action performed correctly with good efficiency."

_MOCK_CLAUDE_RESPONSE_JSON = json.dumps({
    "score": _MOCK_SCORE,
    "thumbs": "up",
    "reasoning": _MOCK_REASONING,
    "criteria_scores": _MOCK_CRITERIA_SCORES,
})


def _mock_claude_response() -> MagicMock:
    """Return a mock Anthropic messages.create response."""
    content_block = MagicMock()
    content_block.type = "text"
    content_block.text = _MOCK_CLAUDE_RESPONSE_JSON
    response = MagicMock()
    response.content = [content_block]
    return response


async def _setup(client: AsyncClient) -> tuple[dict, dict, dict]:
    r = await client.post("/v1/tenants", json={"name": f"AutoJudgeCo-{uuid.uuid4()}"})
    assert r.status_code == 201
    tenant = r.json()
    headers = {"X-API-Key": tenant["initial_api_key"]}
    r = await client.post("/v1/agents", json={"name": "judge-agent"}, headers=headers)
    assert r.status_code == 201
    return tenant, r.json(), headers


async def _log_action(client: AsyncClient, agent_id: str, headers: dict) -> dict:
    r = await client.post(
        f"/v1/agents/{agent_id}/actions",
        json={
            "tool_name": "search_web",
            "input_params": {"query": "test"},
            "output_result": {"results": ["a", "b"]},
            "status": "success",
            "duration_ms": 300,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# auto-evaluate single action
# ---------------------------------------------------------------------------

@patch("crewlayer.core.evaluation.autojudge.anthropic.AsyncAnthropic")
async def test_auto_evaluate_creates_evaluation(mock_cls: MagicMock, client: AsyncClient) -> None:
    mock_instance = AsyncMock()
    mock_instance.messages.create = AsyncMock(return_value=_mock_claude_response())
    mock_cls.return_value = mock_instance

    _, agent, headers = await _setup(client)
    action = await _log_action(client, agent["id"], headers)

    r = await client.post(
        f"/v1/agents/{agent['id']}/actions/{action['id']}/auto-evaluate",
        json={},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["action_id"] == action["id"]
    assert abs(body["score"] - _MOCK_SCORE) < 0.01
    assert body["thumbs"] == "up"
    assert body["reasoning"] == _MOCK_REASONING
    assert body["criteria_scores"]["correctness"] == pytest.approx(4.5, abs=0.01)
    assert "evaluation_id" in body


@patch("crewlayer.core.evaluation.autojudge.anthropic.AsyncAnthropic")
async def test_auto_evaluate_saves_evaluator_auto(mock_cls: MagicMock, client: AsyncClient) -> None:
    mock_instance = AsyncMock()
    mock_instance.messages.create = AsyncMock(return_value=_mock_claude_response())
    mock_cls.return_value = mock_instance

    _, agent, headers = await _setup(client)
    action = await _log_action(client, agent["id"], headers)

    await client.post(
        f"/v1/agents/{agent['id']}/actions/{action['id']}/auto-evaluate",
        json={},
        headers=headers,
    )

    r = await client.get(f"/v1/agents/{agent['id']}/evaluations", headers=headers)
    assert r.status_code == 200
    evals = r.json()["items"]
    assert len(evals) == 1
    assert evals[0]["evaluator"] == "auto"
    assert evals[0]["criteria_scores"] is not None
    assert "correctness" in evals[0]["criteria_scores"]


@patch("crewlayer.core.evaluation.autojudge.anthropic.AsyncAnthropic")
async def test_auto_evaluate_custom_criteria(mock_cls: MagicMock, client: AsyncClient) -> None:
    custom_response_json = json.dumps({
        "score": 3.5,
        "thumbs": "up",
        "reasoning": "Acceptable.",
        "criteria_scores": {"accuracy": 3.5, "speed": 3.5},
    })
    content_block = MagicMock()
    content_block.type = "text"
    content_block.text = custom_response_json
    mock_response = MagicMock()
    mock_response.content = [content_block]

    mock_instance = AsyncMock()
    mock_instance.messages.create = AsyncMock(return_value=mock_response)
    mock_cls.return_value = mock_instance

    _, agent, headers = await _setup(client)
    action = await _log_action(client, agent["id"], headers)

    r = await client.post(
        f"/v1/agents/{agent['id']}/actions/{action['id']}/auto-evaluate",
        json={"criteria": ["accuracy", "speed"]},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert "accuracy" in body["criteria_scores"]
    assert "speed" in body["criteria_scores"]


async def test_auto_evaluate_unknown_action_returns_404(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    r = await client.post(
        f"/v1/agents/{agent['id']}/actions/{uuid.uuid4()}/auto-evaluate",
        json={},
        headers=headers,
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# batch auto-evaluate
# ---------------------------------------------------------------------------

@patch("crewlayer.core.evaluation.autojudge.anthropic.AsyncAnthropic")
async def test_batch_auto_evaluate_skips_already_evaluated(
    mock_cls: MagicMock, client: AsyncClient
) -> None:
    mock_instance = AsyncMock()
    mock_instance.messages.create = AsyncMock(return_value=_mock_claude_response())
    mock_cls.return_value = mock_instance

    _, agent, headers = await _setup(client)
    action = await _log_action(client, agent["id"], headers)

    # Submit an auto-eval manually
    await client.post(
        f"/v1/agents/{agent['id']}/actions/{action['id']}/auto-evaluate",
        json={},
        headers=headers,
    )

    # Batch should report 0 pending (already evaluated)
    r = await client.post(
        f"/v1/agents/{agent['id']}/actions/auto-evaluate-batch",
        json={"limit": 50},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["job_started"] is True
    assert body["actions_pending"] == 0


async def test_batch_auto_evaluate_returns_pending_count(client: AsyncClient) -> None:
    _, agent, headers = await _setup(client)
    # Log 3 actions without evaluating them
    for _ in range(3):
        await _log_action(client, agent["id"], headers)

    r = await client.post(
        f"/v1/agents/{agent['id']}/actions/auto-evaluate-batch",
        json={"limit": 50},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["job_started"] is True
    assert body["actions_pending"] == 3


# ---------------------------------------------------------------------------
# summary includes new fields
# ---------------------------------------------------------------------------

@patch("crewlayer.core.evaluation.autojudge.anthropic.AsyncAnthropic")
async def test_summary_includes_auto_evaluated_count(
    mock_cls: MagicMock, client: AsyncClient
) -> None:
    mock_instance = AsyncMock()
    mock_instance.messages.create = AsyncMock(return_value=_mock_claude_response())
    mock_cls.return_value = mock_instance

    _, agent, headers = await _setup(client)
    action1 = await _log_action(client, agent["id"], headers)
    action2 = await _log_action(client, agent["id"], headers)

    # One auto eval
    await client.post(
        f"/v1/agents/{agent['id']}/actions/{action1['id']}/auto-evaluate",
        json={},
        headers=headers,
    )
    # One human eval
    await client.post(
        f"/v1/agents/{agent['id']}/actions/{action2['id']}/evaluate",
        json={"rating_thumbs": "up", "rating_score": 4.0},
        headers=headers,
    )

    r = await client.get(f"/v1/agents/{agent['id']}/evaluations/summary", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["auto_evaluated_count"] == 1
    assert body["human_evaluated_count"] == 1
    assert body["total_evaluations"] == 2
    assert isinstance(body["criteria_averages"], dict)
    assert "correctness" in body["criteria_averages"]
