import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class WebhookCreate(BaseModel):
    url: str
    events: list[str]
    secret: str
    active: bool = True


class WebhookResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    url: str
    events: list[str]
    active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class DeliveryResponse(BaseModel):
    id: uuid.UUID
    webhook_id: uuid.UUID
    event: str
    payload: dict[str, Any]
    status: str
    attempts: int
    last_attempt_at: datetime | None
    response_status: int | None

    model_config = {"from_attributes": True}


class DeliveryListResponse(BaseModel):
    items: list[DeliveryResponse]
    count: int
