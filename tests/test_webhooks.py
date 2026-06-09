"""Webhook system tests: CRUD, dispatch, HMAC signing, retry, tenant isolation."""
import asyncio
import hashlib
import hmac
import json
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import AsyncMock

from crewlayer.core.webhooks.dispatcher import dispatch
from crewlayer.db.models import DeliveryStatus, WebhookDelivery, WebhookEndpoint

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _setup(client: AsyncClient) -> tuple[dict, dict]:
    """Create tenant; return (tenant, headers)."""
    r = await client.post("/v1/tenants", json={"name": f"HookCo-{uuid.uuid4()}"})
    assert r.status_code == 201
    tenant = r.json()
    return tenant, {"X-API-Key": tenant["initial_api_key"]}


async def _register(
    client: AsyncClient,
    headers: dict,
    url: str = "https://example.com/hook",
    events: list[str] | None = None,
    secret: str = "s3cr3t",
) -> dict:
    r = await client.post(
        "/v1/webhooks",
        json={"url": url, "events": events or ["action.logged"], "secret": secret},
        headers=headers,
    )
    assert r.status_code == 201
    return r.json()


async def _wait_tasks() -> None:
    """Yield control until all background tasks spawned in this event loop complete."""
    while True:
        pending = [
            t for t in asyncio.all_tasks()
            if t != asyncio.current_task() and not t.done()
        ]
        if not pending:
            break
        await asyncio.gather(*pending, return_exceptions=True)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

async def test_register_webhook_returns_endpoint(client: AsyncClient) -> None:
    _, headers = await _setup(client)

    r = await client.post(
        "/v1/webhooks",
        json={"url": "https://example.com/hook", "events": ["action.logged"], "secret": "abc"},
        headers=headers,
    )

    assert r.status_code == 201
    data = r.json()
    assert data["url"] == "https://example.com/hook"
    assert data["events"] == ["action.logged"]
    assert data["active"] is True
    assert "secret" not in data  # secret must never be exposed


async def test_list_webhooks(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    await _register(client, headers, url="https://a.example.com/hook")
    await _register(client, headers, url="https://b.example.com/hook")

    r = await client.get("/v1/webhooks", headers=headers)

    assert r.status_code == 200
    assert len(r.json()) == 2


async def test_delete_webhook(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    wh = await _register(client, headers)

    r = await client.delete(f"/v1/webhooks/{wh['id']}", headers=headers)
    assert r.status_code == 204

    r = await client.get("/v1/webhooks", headers=headers)
    assert r.json() == []


async def test_delete_foreign_webhook_returns_404(client: AsyncClient) -> None:
    _, headers_a = await _setup(client)
    _, headers_b = await _setup(client)
    wh_a = await _register(client, headers_a)

    r = await client.delete(f"/v1/webhooks/{wh_a['id']}", headers=headers_b)
    assert r.status_code == 404


async def test_list_webhooks_tenant_isolation(client: AsyncClient) -> None:
    _, headers_a = await _setup(client)
    _, headers_b = await _setup(client)
    await _register(client, headers_a)

    r = await client.get("/v1/webhooks", headers=headers_b)
    assert r.json() == []


# ---------------------------------------------------------------------------
# Dispatch — delivery created, success recorded
# ---------------------------------------------------------------------------

async def test_dispatch_creates_delivery_on_success(
    client: AsyncClient, db: AsyncSession, mocker: pytest.MonkeyPatch
) -> None:
    tenant, headers = await _setup(client)
    endpoint = await _register(client, headers, events=["action.logged"], secret="mysecret")

    mocker.patch(
        "crewlayer.core.webhooks.dispatcher._http_post",
        new=AsyncMock(return_value=(200, True)),
    )

    tenant_id = uuid.UUID(tenant["id"])
    tasks = await dispatch(tenant_id, "action.logged", {"test": "payload"})
    await asyncio.gather(*tasks)

    result = await db.execute(
        select(WebhookDelivery).where(WebhookDelivery.webhook_id == uuid.UUID(endpoint["id"]))
    )
    delivery = result.scalar_one()
    assert delivery.status == DeliveryStatus.success
    assert delivery.attempts == 1
    assert delivery.response_status == 200
    assert delivery.event == "action.logged"


async def test_dispatch_does_not_fire_for_unsubscribed_event(
    client: AsyncClient, db: AsyncSession, mocker: pytest.MonkeyPatch
) -> None:
    tenant, headers = await _setup(client)
    await _register(client, headers, events=["action.logged"])

    mock_post = mocker.patch(
        "crewlayer.core.webhooks.dispatcher._http_post",
        new=AsyncMock(return_value=(200, True)),
    )

    tasks = await dispatch(uuid.UUID(tenant["id"]), "context.updated", {})
    await asyncio.gather(*tasks)

    mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# HMAC-SHA256 signature
# ---------------------------------------------------------------------------

async def test_dispatch_sends_correct_hmac_signature(
    client: AsyncClient, db: AsyncSession, mocker: pytest.MonkeyPatch
) -> None:
    secret = "super-secret-key"
    tenant, headers = await _setup(client)
    await _register(client, headers, events=["action.logged"], secret=secret)

    captured: list[tuple[str, bytes, dict[str, str]]] = []

    async def fake_http_post(url: str, body: bytes, hdrs: dict[str, str]) -> tuple[int, bool]:
        captured.append((url, body, hdrs))
        return 200, True

    mocker.patch("crewlayer.core.webhooks.dispatcher._http_post", new=fake_http_post)

    payload = {"action_id": "abc123"}
    tasks = await dispatch(uuid.UUID(tenant["id"]), "action.logged", payload)
    await asyncio.gather(*tasks)

    assert len(captured) == 1
    _, body, sent_headers = captured[0]

    expected_body = json.dumps(payload, default=str).encode()
    expected_sig = "sha256=" + hmac.new(secret.encode(), expected_body, hashlib.sha256).hexdigest()

    assert sent_headers["X-AgentLayer-Signature"] == expected_sig
    assert sent_headers["X-AgentLayer-Event"] == "action.logged"
    assert body == expected_body


# ---------------------------------------------------------------------------
# Retry with exponential backoff
# ---------------------------------------------------------------------------

async def test_dispatch_retries_on_failure_and_succeeds(
    client: AsyncClient, db: AsyncSession, mocker: pytest.MonkeyPatch
) -> None:
    tenant, headers = await _setup(client)
    endpoint = await _register(client, headers, events=["action.logged"])

    # Fail twice, succeed on third attempt
    mock_post = AsyncMock(side_effect=[(500, False), (500, False), (200, True)])
    mocker.patch("crewlayer.core.webhooks.dispatcher._http_post", new=mock_post)
    # Skip actual sleep to keep tests fast
    mocker.patch("crewlayer.core.webhooks.dispatcher.asyncio.sleep", new=AsyncMock())

    tasks = await dispatch(uuid.UUID(tenant["id"]), "action.logged", {})
    await asyncio.gather(*tasks)

    assert mock_post.call_count == 3

    result = await db.execute(
        select(WebhookDelivery).where(WebhookDelivery.webhook_id == uuid.UUID(endpoint["id"]))
    )
    delivery = result.scalar_one()
    assert delivery.status == DeliveryStatus.success
    assert delivery.attempts == 3


async def test_dispatch_marks_failed_after_max_attempts(
    client: AsyncClient, db: AsyncSession, mocker: pytest.MonkeyPatch
) -> None:
    tenant, headers = await _setup(client)
    endpoint = await _register(client, headers, events=["action.logged"])

    mocker.patch(
        "crewlayer.core.webhooks.dispatcher._http_post",
        new=AsyncMock(return_value=(503, False)),
    )
    mocker.patch("crewlayer.core.webhooks.dispatcher.asyncio.sleep", new=AsyncMock())

    tasks = await dispatch(uuid.UUID(tenant["id"]), "action.logged", {})
    await asyncio.gather(*tasks)

    result = await db.execute(
        select(WebhookDelivery).where(WebhookDelivery.webhook_id == uuid.UUID(endpoint["id"]))
    )
    delivery = result.scalar_one()
    assert delivery.status == DeliveryStatus.failed
    assert delivery.attempts == 3
    assert delivery.response_status == 503


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------

async def test_dispatch_tenant_isolation(
    client: AsyncClient, db: AsyncSession, mocker: pytest.MonkeyPatch
) -> None:
    tenant_a, headers_a = await _setup(client)
    tenant_b, _ = await _setup(client)

    # Only tenant A registers a webhook
    await _register(client, headers_a, events=["action.logged"])

    mock_post = mocker.patch(
        "crewlayer.core.webhooks.dispatcher._http_post",
        new=AsyncMock(return_value=(200, True)),
    )

    # Dispatch event for tenant B — should NOT fire tenant A's webhook
    tasks = await dispatch(uuid.UUID(tenant_b["id"]), "action.logged", {})
    await asyncio.gather(*tasks)

    mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# Delivery history endpoint
# ---------------------------------------------------------------------------

async def test_list_deliveries_returns_history(
    client: AsyncClient, db: AsyncSession, mocker: pytest.MonkeyPatch
) -> None:
    tenant, headers = await _setup(client)
    endpoint = await _register(client, headers, events=["action.logged"])

    mocker.patch(
        "crewlayer.core.webhooks.dispatcher._http_post",
        new=AsyncMock(return_value=(200, True)),
    )
    mocker.patch("crewlayer.core.webhooks.dispatcher.asyncio.sleep", new=AsyncMock())

    tasks = await dispatch(uuid.UUID(tenant["id"]), "action.logged", {"x": 1})
    await asyncio.gather(*tasks)

    # Refresh the session so the test sees the committed delivery
    await db.commit()

    r = await client.get(f"/v1/webhooks/{endpoint['id']}/deliveries", headers=headers)

    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert data["items"][0]["event"] == "action.logged"
    assert data["items"][0]["status"] == "success"


async def test_list_deliveries_foreign_webhook_returns_404(client: AsyncClient) -> None:
    _, headers_a = await _setup(client)
    _, headers_b = await _setup(client)
    wh_a = await _register(client, headers_a)

    r = await client.get(f"/v1/webhooks/{wh_a['id']}/deliveries", headers=headers_b)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Inactive endpoint is skipped
# ---------------------------------------------------------------------------

async def test_inactive_endpoint_not_dispatched(
    client: AsyncClient, db: AsyncSession, mocker: pytest.MonkeyPatch
) -> None:
    tenant, headers = await _setup(client)
    r = await client.post(
        "/v1/webhooks",
        json={"url": "https://example.com/hook", "events": ["action.logged"],
              "secret": "x", "active": False},
        headers=headers,
    )
    assert r.status_code == 201

    mock_post = mocker.patch(
        "crewlayer.core.webhooks.dispatcher._http_post",
        new=AsyncMock(return_value=(200, True)),
    )

    tasks = await dispatch(uuid.UUID(tenant["id"]), "action.logged", {})
    await asyncio.gather(*tasks)

    mock_post.assert_not_called()
