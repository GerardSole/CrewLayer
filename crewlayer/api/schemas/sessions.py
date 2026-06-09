import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from crewlayer.db.models import SessionStatus


class SessionCreate(BaseModel):
    agent_id: uuid.UUID
    metadata: dict[str, Any] = {}


class SessionResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    agent_id: uuid.UUID
    status: SessionStatus
    summary: str | None
    message_count: int
    started_at: datetime
    closed_at: datetime | None
    metadata: dict[str, Any]

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, obj: Any) -> "SessionResponse":
        return cls(
            id=obj.id,
            tenant_id=obj.tenant_id,
            agent_id=obj.agent_id,
            status=obj.status,
            summary=obj.summary,
            message_count=obj.message_count,
            started_at=obj.started_at,
            closed_at=obj.closed_at,
            metadata=obj.metadata_,
        )


class SessionCloseResponse(BaseModel):
    session: SessionResponse
    memories_extracted: int
