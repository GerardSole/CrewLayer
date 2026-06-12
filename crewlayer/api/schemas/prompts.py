"""Pydantic v2 schemas for prompt version control endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class PromptVersionCreate(BaseModel):
    content: str = Field(..., min_length=1)
    description: str | None = None


class PromptVersionResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    agent_id: uuid.UUID
    version: int
    content: str
    description: str | None = None
    is_active: bool
    created_at: datetime
    created_by: uuid.UUID | None = None

    model_config = {"from_attributes": True}


class PromptVersionListResponse(BaseModel):
    items: list[PromptVersionResponse]
    count: int


class DiffLineResponse(BaseModel):
    operation: str   # "equal" | "insert" | "delete"
    content: str
    line_a: int | None = None
    line_b: int | None = None


class PromptDiffResponse(BaseModel):
    version_id_a: uuid.UUID
    version_id_b: uuid.UUID
    lines: list[DiffLineResponse]
