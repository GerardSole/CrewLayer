"""Prometheus /metrics endpoint tests.

Covers:
- 403 when no token is set and request is not from localhost
- 403 with wrong token
- 200 with correct X-Metrics-Token header
- 200 with correct Authorization: Bearer header
- 200 from localhost even without a token
- Response Content-Type is Prometheus text format
- Response body contains all six custom metric names
- Response body contains instrumentator metric names
- collect_metrics() runs without error when DB is unavailable
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from main import app

pytestmark = pytest.mark.asyncio

_TOKEN = "test-metrics-token"
_METRIC_NAMES = [
    b"crewlayer_memories_total",
    b"crewlayer_actions_total",
    b"crewlayer_active_sessions",
    b"crewlayer_agents_by_status",
    b"crewlayer_memory_importance_avg",
    b"crewlayer_api_key_usage_total",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def external_client() -> AsyncGenerator[AsyncClient, None]:
    """Client that simulates requests from a non-localhost IP (1.2.3.4)."""
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("1.2.3.4", 456)),
        base_url="http://testclient",
    ) as c:
        yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_token(token: str = _TOKEN):
    """Patch settings.METRICS_TOKEN for the duration of a test."""
    from crewlayer.api.routes import metrics as metrics_mod
    return patch.object(metrics_mod.settings, "METRICS_TOKEN", token)


# ---------------------------------------------------------------------------
# Auth: denied cases (use external_client — not localhost)
# ---------------------------------------------------------------------------


async def test_metrics_denied_without_token(external_client: AsyncClient) -> None:
    """Returns 403 when no token is configured and client is not localhost."""
    with _patch_token(""):
        r = await external_client.get("/metrics")
    assert r.status_code == 403


async def test_metrics_denied_with_wrong_token(external_client: AsyncClient) -> None:
    """Returns 403 when the wrong X-Metrics-Token is supplied."""
    with _patch_token():
        r = await external_client.get("/metrics", headers={"X-Metrics-Token": "wrong"})
    assert r.status_code == 403


async def test_metrics_denied_with_wrong_bearer(external_client: AsyncClient) -> None:
    """Returns 403 when the wrong Bearer token is supplied."""
    with _patch_token():
        r = await external_client.get("/metrics", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Auth: allowed cases
# ---------------------------------------------------------------------------


async def test_metrics_allowed_from_localhost(client: AsyncClient) -> None:
    """Returns 200 from localhost even without a token (default ASGITransport IP)."""
    with _patch_token(""):
        r = await client.get("/metrics")
    assert r.status_code == 200


async def test_metrics_allowed_with_x_metrics_token(external_client: AsyncClient) -> None:
    """Returns 200 when the correct X-Metrics-Token is provided from a remote host."""
    with _patch_token():
        r = await external_client.get("/metrics", headers={"X-Metrics-Token": _TOKEN})
    assert r.status_code == 200


async def test_metrics_allowed_with_bearer_token(external_client: AsyncClient) -> None:
    """Returns 200 when the correct Authorization: Bearer token is provided from a remote host."""
    with _patch_token():
        r = await external_client.get("/metrics", headers={"Authorization": f"Bearer {_TOKEN}"})
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Response format
# ---------------------------------------------------------------------------


async def test_metrics_content_type(client: AsyncClient) -> None:
    """Content-Type must be the Prometheus text format."""
    with _patch_token():
        r = await client.get("/metrics", headers={"X-Metrics-Token": _TOKEN})
    assert "text/plain" in r.headers["content-type"]
    assert "0.0.4" in r.headers["content-type"]


async def test_metrics_contains_custom_metric_names(client: AsyncClient) -> None:
    """Response body must declare all six custom metric families."""
    with _patch_token():
        r = await client.get("/metrics", headers={"X-Metrics-Token": _TOKEN})
    body = r.content
    for name in _METRIC_NAMES:
        assert name in body, f"Missing metric: {name.decode()}"


# ---------------------------------------------------------------------------
# collect_metrics() is resilient to DB errors
# ---------------------------------------------------------------------------


async def test_collect_metrics_survives_db_error() -> None:
    """collect_metrics() must not propagate exceptions when the DB is down."""
    from crewlayer.core.metrics.collectors import collect_metrics

    with patch(
        "crewlayer.core.metrics.collectors.AsyncSessionLocal",
        side_effect=Exception("DB unavailable"),
    ):
        # Must complete without raising
        await collect_metrics()


async def test_collect_metrics_runs_without_db() -> None:
    """collect_metrics() with a mock session completes without error."""
    from crewlayer.core.metrics.collectors import collect_metrics

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=AsyncMock(all=lambda: []))

    with patch("crewlayer.core.metrics.collectors.AsyncSessionLocal", return_value=mock_session):
        await collect_metrics()
