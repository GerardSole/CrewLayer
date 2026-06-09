import uuid
from datetime import datetime

from pydantic import BaseModel


class AuditLogEntry(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    api_key_id: uuid.UUID | None
    actor_key_name: str
    method: str
    path: str
    resource_type: str | None
    resource_id: str | None
    ip_address: str | None
    status_code: int
    timestamp: datetime

    model_config = {"from_attributes": True}


class AuditLogListResponse(BaseModel):
    items: list[AuditLogEntry]
    next_cursor: str | None
