import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ContextWrite(BaseModel):
    value: dict[str, Any]
    written_by: uuid.UUID | None = None
    expires_at: datetime | None = None
    expected_version: int | None = Field(
        default=None,
        description=(
            "Optimistic lock: pass the version you last read. "
            "Omit to skip the check. Use 0 to assert the key does not yet exist."
        ),
    )


class ContextEntryResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    namespace: str
    key: str
    value: dict[str, Any]
    written_by: uuid.UUID | None = None
    version: int
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ContextNamespaceResponse(BaseModel):
    namespace: str
    entries: list[ContextEntryResponse]
    count: int


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

class ContextHistoryEntry(BaseModel):
    id: uuid.UUID
    namespace: str
    key: str
    value: dict[str, Any] | None
    version: int
    written_by: uuid.UUID | None = None
    operation: str
    timestamp: datetime

    model_config = {"from_attributes": True}


class ContextHistoryResponse(BaseModel):
    namespace: str
    key: str
    entries: list[ContextHistoryEntry]
    next_cursor: str | None = None


class RollbackRequest(BaseModel):
    target_version: int = Field(..., ge=1, description="History version to restore.")
    written_by: uuid.UUID | None = None


class RollbackResponse(BaseModel):
    namespace: str
    key: str
    restored_version: int
    new_version: int
    entry: ContextEntryResponse
