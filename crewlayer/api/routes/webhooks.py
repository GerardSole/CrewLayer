import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from crewlayer.api.deps import DbDep, TenantDep
from crewlayer.api.schemas.webhooks import (
    DeliveryListResponse,
    DeliveryResponse,
    WebhookCreate,
    WebhookResponse,
    WebhookTestResponse,
    WebhookUpdate,
)
from crewlayer.db.models import DeliveryStatus, WebhookDelivery, WebhookEndpoint

router = APIRouter()


@router.post("/webhooks", response_model=WebhookResponse, status_code=status.HTTP_201_CREATED)
async def register_webhook(
    body: WebhookCreate,
    tenant: TenantDep,
    db: DbDep,
) -> WebhookResponse:
    """Register an outgoing webhook endpoint for this tenant."""
    endpoint = WebhookEndpoint(
        tenant_id=tenant.id,
        url=body.url,
        events=body.events,
        secret=body.secret,
        active=body.active,
    )
    db.add(endpoint)
    await db.commit()
    await db.refresh(endpoint)
    return WebhookResponse.model_validate(endpoint)


@router.get("/webhooks", response_model=list[WebhookResponse])
async def list_webhooks(tenant: TenantDep, db: DbDep) -> list[WebhookResponse]:
    """List all webhook endpoints registered for this tenant."""
    result = await db.execute(
        select(WebhookEndpoint)
        .where(WebhookEndpoint.tenant_id == tenant.id)
        .order_by(WebhookEndpoint.created_at.desc())
    )
    return [WebhookResponse.model_validate(e) for e in result.scalars().all()]


@router.patch("/webhooks/{webhook_id}", response_model=WebhookResponse)
async def update_webhook(
    webhook_id: uuid.UUID, body: WebhookUpdate, tenant: TenantDep, db: DbDep
) -> WebhookResponse:
    """Toggle active status of a webhook endpoint."""
    result = await db.execute(
        select(WebhookEndpoint).where(
            WebhookEndpoint.id == webhook_id,
            WebhookEndpoint.tenant_id == tenant.id,
        )
    )
    endpoint = result.scalar_one_or_none()
    if endpoint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook no encontrado")
    if body.active is not None:
        endpoint.active = body.active
    await db.commit()
    await db.refresh(endpoint)
    return WebhookResponse.model_validate(endpoint)


@router.delete("/webhooks/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(webhook_id: uuid.UUID, tenant: TenantDep, db: DbDep) -> None:
    """Delete a webhook endpoint. Returns 404 if not found or belongs to another tenant."""
    result = await db.execute(
        select(WebhookEndpoint).where(
            WebhookEndpoint.id == webhook_id,
            WebhookEndpoint.tenant_id == tenant.id,
        )
    )
    endpoint = result.scalar_one_or_none()
    if endpoint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook no encontrado")
    await db.delete(endpoint)
    await db.commit()


@router.post("/webhooks/{webhook_id}/test", response_model=WebhookTestResponse)
async def test_webhook(webhook_id: uuid.UUID, tenant: TenantDep, db: DbDep) -> WebhookTestResponse:
    """Send a test payload to a webhook endpoint and record the delivery."""
    result = await db.execute(
        select(WebhookEndpoint).where(
            WebhookEndpoint.id == webhook_id,
            WebhookEndpoint.tenant_id == tenant.id,
        )
    )
    endpoint = result.scalar_one_or_none()
    if endpoint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook no encontrado")

    payload: dict = {
        "event": "test",
        "webhook_id": str(webhook_id),
        "timestamp": datetime.now(UTC).isoformat(),
        "message": "This is a test delivery from CrewLayer.",
    }
    body = json.dumps(payload, default=str).encode()
    sig = "sha256=" + hmac.new(endpoint.secret.encode(), body, hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-AgentLayer-Signature": sig,
        "X-AgentLayer-Event": "test",
    }

    response_status: int | None = None
    ok = False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(endpoint.url, content=body, headers=headers)
            response_status = r.status_code
            ok = r.status_code < 300
    except Exception:
        pass

    delivery = WebhookDelivery(
        webhook_id=endpoint.id,
        event="test",
        payload=payload,
        status=DeliveryStatus.success if ok else DeliveryStatus.failed,
        attempts=1,
        last_attempt_at=datetime.now(UTC),
        response_status=response_status,
    )
    db.add(delivery)
    await db.commit()

    return WebhookTestResponse(
        status="delivered" if ok else "failed",
        response_status=response_status,
    )


@router.get("/webhooks/{webhook_id}/deliveries", response_model=DeliveryListResponse)
async def list_deliveries(webhook_id: uuid.UUID, tenant: TenantDep, db: DbDep) -> DeliveryListResponse:
    """List delivery history for a webhook endpoint (most recent first)."""
    # Verify ownership
    endpoint_result = await db.execute(
        select(WebhookEndpoint).where(
            WebhookEndpoint.id == webhook_id,
            WebhookEndpoint.tenant_id == tenant.id,
        )
    )
    if endpoint_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook no encontrado")

    deliveries_result = await db.execute(
        select(WebhookDelivery)
        .where(WebhookDelivery.webhook_id == webhook_id)
        .order_by(WebhookDelivery.last_attempt_at.desc().nulls_last())
    )
    items = [DeliveryResponse.model_validate(d) for d in deliveries_result.scalars().all()]
    return DeliveryListResponse(items=items, count=len(items))
