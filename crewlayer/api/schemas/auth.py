import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from crewlayer.db.models import PlanEnum


class TenantCreate(BaseModel):
    name: str


class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    plan: PlanEnum
    created_at: datetime


class TenantCreatedResponse(TenantResponse):
    """Returned only on tenant creation — includes bootstrap API key in cleartext."""
    initial_api_key: str


class ApiKeyCreate(BaseModel):
    name: str
    scopes: list[str] = []
    expires_at: datetime | None = None


class ApiKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    scopes: list[str]
    last_used_at: datetime | None
    expires_at: datetime | None


class ApiKeyCreatedResponse(ApiKeyResponse):
    """Returned only on key creation — includes the raw key. Never shown again."""
    key: str
