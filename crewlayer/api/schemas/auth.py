import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from crewlayer.db.models import PlanEnum, ScopeEnum


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


_VALID_SCOPES = {s.value for s in ScopeEnum}


class ApiKeyCreate(BaseModel):
    name: str
    scopes: list[str] = []
    agent_ids: list[uuid.UUID] = []
    expires_at: datetime | None = None

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, v: list[str]) -> list[str]:
        invalid = [s for s in v if s not in _VALID_SCOPES]
        if invalid:
            raise ValueError(
                f"Scopes inválidos: {invalid}. "
                f"Válidos: {sorted(_VALID_SCOPES)}"
            )
        return v


class ApiKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    scopes: list[str]
    agent_ids: list[uuid.UUID]
    last_used_at: datetime | None
    expires_at: datetime | None


class ApiKeyCreatedResponse(ApiKeyResponse):
    """Returned only on key creation — includes the raw key. Never shown again."""
    key: str
