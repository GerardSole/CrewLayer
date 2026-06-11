import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from crewlayer.db.models import ActionStatus, ReplayStatusEnum


class ActionCreate(BaseModel):
    session_id: uuid.UUID | None = None
    tool_name: str
    input_params: dict[str, Any] = Field(default_factory=dict)
    output_result: dict[str, Any] = Field(default_factory=dict)
    status: ActionStatus
    duration_ms: int | None = None
    error_msg: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    agent_id: uuid.UUID
    session_id: uuid.UUID | None = None
    tool_name: str
    input_params: dict[str, Any]
    output_result: dict[str, Any]
    status: ActionStatus
    duration_ms: int | None = None
    error_msg: str | None = None
    timestamp: datetime
    metadata: dict[str, Any] = Field(validation_alias="metadata_", default_factory=dict)

    model_config = {"from_attributes": True, "populate_by_name": True}


class ActionListResponse(BaseModel):
    items: list[ActionResponse]
    count: int
    next_cursor: str | None = None


class ToolStatResponse(BaseModel):
    tool_name: str
    count: int
    avg_duration_ms: float | None = None
    error_rate: float


class ActionStatsResponse(BaseModel):
    total_actions: int
    error_rate: float
    avg_duration_ms: float | None = None
    by_tool: list[ToolStatResponse]


class ReplayCreate(BaseModel):
    from_timestamp: datetime
    to_timestamp: datetime
    speed: float = Field(default=1.0, ge=0.1, le=10000.0)

    @model_validator(mode="after")
    def _check_range(self) -> "ReplayCreate":
        if self.from_timestamp >= self.to_timestamp:
            raise ValueError("from_timestamp must be before to_timestamp")
        return self


class ReplayResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    agent_id: uuid.UUID
    status: ReplayStatusEnum
    from_timestamp: datetime
    to_timestamp: datetime
    speed: float
    action_count: int
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class ReplayListResponse(BaseModel):
    items: list[ReplayResponse]
    count: int
