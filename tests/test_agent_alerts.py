"""Tests for automatic agent failure alerts: consecutive errors, error rate, config endpoints."""
import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

_ERROR_ACTION = {
    "tool_name": "run_query",
    "input_params": {},
    "output_result": {},
    "status": "error",
    "error_msg": "boom",
}
_SUCCESS_ACTION = {
    "tool_name": "run_query",
    "input_params": {},
    "output_result": {"ok": True},
    "status": "success",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _setup(client: AsyncClient) -> tuple[dict, dict]:
    r = await client.post("/v1/tenants", json={"name": f"AlertCo-{uuid.uuid4()}"})
    assert r.status_code == 201
    tenant = r.json()
    return tenant, {"X-API-Key": tenant["initial_api_key"]}


async def _create_agent(client: AsyncClient, headers: dict, config: dict | None = None) -> dict:
    body: dict = {"name": f"bot-{uuid.uuid4()}", "description": "test"}
    if config is not None:
        body["config"] = config
    r = await client.post("/v1/agents", json=body, headers=headers)
    assert r.status_code == 201
    return r.json()


async def _log_action(
    client: AsyncClient,
    headers: dict,
    agent_id: str,
    action: dict,
) -> dict:
    r = await client.post(f"/v1/agents/{agent_id}/actions", json=action, headers=headers)
    assert r.status_code == 201
    return r.json()


# ---------------------------------------------------------------------------
# Alert config endpoints
# ---------------------------------------------------------------------------

async def test_get_alerts_config_defaults(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)

    r = await client.get(f"/v1/agents/{agent['id']}/alerts/config", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["alerts_enabled"] is True
    assert data["alert_on_consecutive_errors"] == 5
    assert data["alert_on_error_rate_percent"] == 80


async def test_patch_alerts_config_updates_fields(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)

    r = await client.patch(
        f"/v1/agents/{agent['id']}/alerts/config",
        json={"alert_on_consecutive_errors": 3, "alert_on_error_rate_percent": 60},
        headers=headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["alert_on_consecutive_errors"] == 3
    assert data["alert_on_error_rate_percent"] == 60
    assert data["alerts_enabled"] is True  # unchanged


async def test_patch_alerts_config_can_disable(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)

    r = await client.patch(
        f"/v1/agents/{agent['id']}/alerts/config",
        json={"alerts_enabled": False},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["alerts_enabled"] is False

    # Verify GET reflects the change
    r2 = await client.get(f"/v1/agents/{agent['id']}/alerts/config", headers=headers)
    assert r2.json()["alerts_enabled"] is False


# ---------------------------------------------------------------------------
# Consecutive error alert
# ---------------------------------------------------------------------------

async def test_alert_fires_at_consecutive_threshold(
    client: AsyncClient, mocker: pytest.MonkeyPatch
) -> None:
    mock_dispatch = mocker.patch(
        "crewlayer.core.actions.alerts.dispatch", new=AsyncMock(return_value=[])
    )
    _, headers = await _setup(client)
    # threshold=3 so we don't need 5 requests
    agent = await _create_agent(client, headers, config={"alert_on_consecutive_errors": 3})

    await _log_action(client, headers, agent["id"], _ERROR_ACTION)
    mock_dispatch.assert_not_called()

    await _log_action(client, headers, agent["id"], _ERROR_ACTION)
    mock_dispatch.assert_not_called()

    await _log_action(client, headers, agent["id"], _ERROR_ACTION)  # 3rd error → fires
    mock_dispatch.assert_called_once()
    call_kwargs = mock_dispatch.call_args
    assert call_kwargs[0][1] == "agent.alert"
    payload = call_kwargs[0][2]
    assert payload["alert_type"] == "consecutive_errors"
    assert payload["threshold"] == 3
    assert payload["current_value"] == 3


async def test_alert_not_fired_before_threshold(
    client: AsyncClient, mocker: pytest.MonkeyPatch
) -> None:
    mock_dispatch = mocker.patch(
        "crewlayer.core.actions.alerts.dispatch", new=AsyncMock(return_value=[])
    )
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers, config={"alert_on_consecutive_errors": 5})

    for _ in range(4):
        await _log_action(client, headers, agent["id"], _ERROR_ACTION)

    # dispatch should not have been called for agent.alert
    alert_calls = [
        c for c in mock_dispatch.call_args_list if c[0][1] == "agent.alert"
    ]
    assert len(alert_calls) == 0


async def test_alert_resets_on_success(
    client: AsyncClient, mocker: pytest.MonkeyPatch
) -> None:
    mock_dispatch = mocker.patch(
        "crewlayer.core.actions.alerts.dispatch", new=AsyncMock(return_value=[])
    )
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers, config={"alert_on_consecutive_errors": 3})

    # 2 errors, then 1 success (resets counter), then 2 more errors → no alert
    await _log_action(client, headers, agent["id"], _ERROR_ACTION)
    await _log_action(client, headers, agent["id"], _ERROR_ACTION)
    await _log_action(client, headers, agent["id"], _SUCCESS_ACTION)  # reset
    await _log_action(client, headers, agent["id"], _ERROR_ACTION)
    await _log_action(client, headers, agent["id"], _ERROR_ACTION)

    alert_calls = [c for c in mock_dispatch.call_args_list if c[0][1] == "agent.alert"]
    assert len(alert_calls) == 0


async def test_alert_disabled_no_dispatch(
    client: AsyncClient, mocker: pytest.MonkeyPatch
) -> None:
    mock_dispatch = mocker.patch(
        "crewlayer.core.actions.alerts.dispatch", new=AsyncMock(return_value=[])
    )
    _, headers = await _setup(client)
    agent = await _create_agent(
        client, headers,
        config={"alerts_enabled": False, "alert_on_consecutive_errors": 1},
    )

    for _ in range(5):
        await _log_action(client, headers, agent["id"], _ERROR_ACTION)

    alert_calls = [c for c in mock_dispatch.call_args_list if c[0][1] == "agent.alert"]
    assert len(alert_calls) == 0


async def test_alert_counter_resets_after_firing(
    client: AsyncClient, mocker: pytest.MonkeyPatch
) -> None:
    """After the threshold is hit and alert fires, the counter resets. Next N errors fire again."""
    mock_dispatch = mocker.patch(
        "crewlayer.core.actions.alerts.dispatch", new=AsyncMock(return_value=[])
    )
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers, config={"alert_on_consecutive_errors": 2})

    # First batch: 2 errors → 1st alert
    await _log_action(client, headers, agent["id"], _ERROR_ACTION)
    await _log_action(client, headers, agent["id"], _ERROR_ACTION)

    alert_calls_1 = [c for c in mock_dispatch.call_args_list if c[0][1] == "agent.alert"]
    assert len(alert_calls_1) == 1

    # Second batch: 2 more errors → 2nd alert
    await _log_action(client, headers, agent["id"], _ERROR_ACTION)
    await _log_action(client, headers, agent["id"], _ERROR_ACTION)

    alert_calls_2 = [c for c in mock_dispatch.call_args_list if c[0][1] == "agent.alert"]
    assert len(alert_calls_2) == 2


async def test_alert_payload_contains_agent_info(
    client: AsyncClient, mocker: pytest.MonkeyPatch
) -> None:
    mock_dispatch = mocker.patch(
        "crewlayer.core.actions.alerts.dispatch", new=AsyncMock(return_value=[])
    )
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers, config={"alert_on_consecutive_errors": 1})

    action = await _log_action(client, headers, agent["id"], _ERROR_ACTION)

    mock_dispatch.assert_called_once()
    payload = mock_dispatch.call_args[0][2]
    assert payload["agent_id"] == agent["id"]
    assert payload["agent_name"] == agent["name"]
    assert payload["last_action_id"] == action["id"]
    assert "timestamp" in payload


# ---------------------------------------------------------------------------
# Error rate alert
# ---------------------------------------------------------------------------

async def test_alert_fires_on_error_rate(
    client: AsyncClient, mocker: pytest.MonkeyPatch
) -> None:
    """Error-rate alert fires once a full 20-action window shows ≥threshold% errors."""
    mock_dispatch = mocker.patch(
        "crewlayer.core.actions.alerts.dispatch", new=AsyncMock(return_value=[])
    )
    _, headers = await _setup(client)
    # High consecutive threshold so only the rate alert can fire.
    # Rate threshold = 50%; 20 actions alternating S/E = 10 errors / 20 total = 50%.
    agent = await _create_agent(
        client, headers,
        config={"alert_on_consecutive_errors": 99, "alert_on_error_rate_percent": 50},
    )

    for _ in range(10):
        await _log_action(client, headers, agent["id"], _SUCCESS_ACTION)
        await _log_action(client, headers, agent["id"], _ERROR_ACTION)

    # After the 20th action (an error), rate = 10/20 = 50% → fires
    alert_calls = [c for c in mock_dispatch.call_args_list if c[0][1] == "agent.alert"]
    assert len(alert_calls) >= 1
    rate_alerts = [c for c in alert_calls if c[0][2]["alert_type"] == "error_rate"]
    assert len(rate_alerts) >= 1
    assert rate_alerts[-1][0][2]["threshold"] == 50


async def test_alert_error_rate_not_fired_below_threshold(
    client: AsyncClient, mocker: pytest.MonkeyPatch
) -> None:
    """Rate alert does not fire when error rate is below threshold even with a full window."""
    mock_dispatch = mocker.patch(
        "crewlayer.core.actions.alerts.dispatch", new=AsyncMock(return_value=[])
    )
    _, headers = await _setup(client)
    # Rate threshold = 80%; log 20 actions with 14 errors = 70% → below threshold
    agent = await _create_agent(
        client, headers,
        config={"alert_on_consecutive_errors": 99, "alert_on_error_rate_percent": 80},
    )

    for _ in range(6):
        await _log_action(client, headers, agent["id"], _SUCCESS_ACTION)
    for _ in range(14):
        await _log_action(client, headers, agent["id"], _ERROR_ACTION)

    alert_calls = [c for c in mock_dispatch.call_args_list if c[0][1] == "agent.alert"]
    assert len(alert_calls) == 0


async def test_alert_error_rate_not_fired_when_window_not_full(
    client: AsyncClient, mocker: pytest.MonkeyPatch
) -> None:
    """Rate alert requires a full 20-action window; fewer actions never trigger it."""
    mock_dispatch = mocker.patch(
        "crewlayer.core.actions.alerts.dispatch", new=AsyncMock(return_value=[])
    )
    _, headers = await _setup(client)
    agent = await _create_agent(
        client, headers,
        config={"alert_on_consecutive_errors": 99, "alert_on_error_rate_percent": 50},
    )

    # Only 5 error actions — 100% error rate but window is not full
    for _ in range(5):
        await _log_action(client, headers, agent["id"], _ERROR_ACTION)

    alert_calls = [c for c in mock_dispatch.call_args_list if c[0][1] == "agent.alert"]
    assert len(alert_calls) == 0
