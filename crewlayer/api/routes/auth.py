import secrets
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from crewlayer.api.deps import DbDep, TenantDep
from crewlayer.api.schemas.auth import (
    ApiKeyCreate,
    ApiKeyCreatedResponse,
    ApiKeyResponse,
    TenantCreate,
    TenantCreatedResponse,
)
from crewlayer.core.security import hash_key
from crewlayer.db.models import ApiKey, Tenant

router = APIRouter()


def _generate_api_key(key_id: uuid.UUID) -> str:
    """Build a key string that encodes its own DB id for fast lookup.

    Format: crwl_{uuid_hex32}_{urlsafe_random32}  →  70 chars total (< bcrypt 72-byte limit)
    """
    return f"crwl_{key_id.hex}_{secrets.token_urlsafe(24)}"


def _make_api_key_record(
    key_id: uuid.UUID,
    tenant_id: uuid.UUID,
    name: str,
    scopes: list[str],
    raw_key: str,
    expires_at: datetime | None = None,
) -> tuple[ApiKey, str]:
    """Return (ApiKey ORM object, raw_key) without adding to any session."""
    return ApiKey(
        id=key_id,
        tenant_id=tenant_id,
        name=name,
        scopes=scopes,
        key_hash=hash_key(raw_key),
        expires_at=expires_at,
    ), raw_key


@router.post("/tenants", response_model=TenantCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(data: TenantCreate, db: DbDep) -> TenantCreatedResponse:
    """Create a new tenant and return it with a bootstrap API key.

    The bootstrap key is only shown here. Store it securely — it cannot be retrieved again.
    """
    tenant = Tenant(name=data.name)
    db.add(tenant)
    await db.flush()  # populate tenant.id before creating the key

    key_id = uuid.uuid4()
    raw_key = _generate_api_key(key_id)
    initial_key = ApiKey(
        id=key_id,
        tenant_id=tenant.id,
        name="default",
        scopes=[],
        key_hash=hash_key(raw_key),
    )
    db.add(initial_key)
    await db.commit()
    await db.refresh(tenant)

    return TenantCreatedResponse(
        id=tenant.id,
        name=tenant.name,
        plan=tenant.plan,
        created_at=tenant.created_at,
        initial_api_key=raw_key,
    )


@router.post("/api-keys", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    data: ApiKeyCreate,
    tenant: TenantDep,
    db: DbDep,
) -> ApiKeyCreatedResponse:
    """Create a new API key for the authenticated tenant.

    The raw key is only returned in this response. Store it securely.
    """
    key_id = uuid.uuid4()
    raw_key = _generate_api_key(key_id)

    api_key = ApiKey(
        id=key_id,
        tenant_id=tenant.id,
        name=data.name,
        scopes=data.scopes,
        agent_ids=data.agent_ids,
        key_hash=hash_key(raw_key),
        expires_at=data.expires_at,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    return ApiKeyCreatedResponse(
        id=api_key.id,
        name=api_key.name,
        scopes=api_key.scopes,
        agent_ids=api_key.agent_ids,
        last_used_at=api_key.last_used_at,
        expires_at=api_key.expires_at,
        key=raw_key,
    )


@router.get("/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(tenant: TenantDep, db: DbDep) -> list[ApiKeyResponse]:
    """List all API keys for the authenticated tenant (hashes are never exposed)."""
    result = await db.execute(
        select(ApiKey).where(ApiKey.tenant_id == tenant.id).order_by(ApiKey.name)
    )
    return [ApiKeyResponse.model_validate(k) for k in result.scalars().all()]


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(key_id: uuid.UUID, tenant: TenantDep, db: DbDep) -> None:
    """Revoke an API key.  Returns 404 if the key doesn't exist or belongs to another tenant."""
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.id == key_id)
        .where(ApiKey.tenant_id == tenant.id)
    )
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key no encontrada")

    await db.delete(api_key)
    await db.commit()
