import asyncio
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from crewlayer.core.config import settings
from crewlayer.db.models import DeliveryStatus, WebhookDelivery, WebhookEndpoint

_MAX_ATTEMPTS = 3

# Dedicated no-pool engine for background delivery tasks.
# NullPool avoids stale connections when tasks outlive the event loop that created them.
_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def dispatch(
    tenant_id: uuid.UUID,
    event: str,
    payload: dict[str, Any],
) -> list[asyncio.Task[None]]:
    """Find active webhook endpoints subscribed to *event* and schedule delivery.

    Returns the list of spawned delivery tasks so callers (e.g. tests) can
    await them. Production routes should fire-and-forget via asyncio.create_task.
    """
    async with _session_factory() as db:
        result = await db.execute(
            select(WebhookEndpoint).where(
                WebhookEndpoint.tenant_id == tenant_id,
                WebhookEndpoint.active.is_(True),
                WebhookEndpoint.events.contains([event]),  # events @> ARRAY['event']
            )
        )
        endpoints = list(result.scalars().all())

    tasks: list[asyncio.Task[None]] = []
    for endpoint in endpoints:
        task = asyncio.create_task(
            _deliver_with_retry(
                endpoint_id=endpoint.id,
                url=endpoint.url,
                secret=endpoint.secret,
                event=event,
                payload=payload,
            )
        )
        tasks.append(task)
    return tasks


async def _deliver_with_retry(
    endpoint_id: uuid.UUID,
    url: str,
    secret: str,
    event: str,
    payload: dict[str, Any],
) -> None:
    """Create a delivery record then attempt HTTP delivery up to _MAX_ATTEMPTS times."""
    body = json.dumps(payload, default=str).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-AgentLayer-Signature": sig,
        "X-AgentLayer-Event": event,
    }

    # Create the delivery record before the first attempt
    async with _session_factory() as db:
        delivery = WebhookDelivery(
            webhook_id=endpoint_id,
            event=event,
            payload=payload,
            status=DeliveryStatus.pending,
            attempts=0,
        )
        db.add(delivery)
        await db.commit()
        await db.refresh(delivery)
        delivery_id = delivery.id

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        async with _session_factory() as db:
            result = await db.execute(
                select(WebhookDelivery).where(WebhookDelivery.id == delivery_id)
            )
            delivery = result.scalar_one()
            delivery.attempts = attempt
            delivery.last_attempt_at = datetime.now(UTC)

            status_code, ok = await _http_post(url, body, headers)
            delivery.response_status = status_code
            delivery.status = DeliveryStatus.success if ok else DeliveryStatus.failed
            await db.commit()

        if ok:
            return

        if attempt < _MAX_ATTEMPTS:
            await asyncio.sleep(2**attempt)  # 2 s, 4 s


async def _http_post(
    url: str,
    body: bytes,
    headers: dict[str, str],
) -> tuple[int | None, bool]:
    """Make one HTTP POST. Isolated so tests can patch it without touching httpx internals."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, content=body, headers=headers)
            return r.status_code, r.status_code < 300
    except Exception:
        return None, False
