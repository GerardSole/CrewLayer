import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class MessageIn(BaseModel):
    role: str = Field(..., examples=["user", "assistant"])
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MessageOut(BaseModel):
    role: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ShortMemoryResponse(BaseModel):
    session_id: str
    messages: list[MessageOut]
    count: int


class RecallRequest(BaseModel):
    query: str
    limit: int = Field(default=10, ge=1, le=100)
    min_similarity: float = Field(default=0.0, ge=0.0, le=1.0)


class MemoryResponse(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    content: str
    summary: str | None = None
    importance: float
    base_importance: float
    tags: list[str]
    created_at: datetime
    similarity: float | None = None

    model_config = {"from_attributes": True}


class RecallResponse(BaseModel):
    query: str
    results: list[MemoryResponse]


class ExtractRequest(BaseModel):
    conversation: str
    session_id: str | None = None


class ExtractResponse(BaseModel):
    extracted_count: int
    memory_ids: list[uuid.UUID]


class MemoryListResponse(BaseModel):
    items: list[MemoryResponse]
    total: int
    page: int
    page_size: int
