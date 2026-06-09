import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.core.redis import get_redis
from crewlayer.core.security import verify_key
from crewlayer.db.models import ApiKey, Tenant
from crewlayer.db.session import get_db

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="API key inválida o expirada",
    headers={"WWW-Authenticate": "ApiKey"},
)


def _parse_key_id(raw_key: str) -> uuid.UUID | None:
    """Extract the key's UUID from 'crwl_{uuid32hex}_{secret}' format.

    Encoding the key ID in the key itself lets us do a direct DB lookup by PK
    instead of scanning all rows and calling bcrypt on each one.
    """
    parts = raw_key.split("_", 2)
    if len(parts) != 3 or parts[0] != "crwl":
        return None
    try:
        return uuid.UUID(parts[1])
    except ValueError:
        return None


async def get_current_tenant(
    db: AsyncSession = Depends(get_db),
    x_api_key: Annotated[str | None, Header()] = None,
) -> Tenant:
    """Validate X-API-Key header and return the owning Tenant.

    Raises 401 for: missing header, malformed key, key not found,
    wrong secret, or expired key.
    """
    if x_api_key is None:
        raise _UNAUTHORIZED

    key_id = _parse_key_id(x_api_key)
    if key_id is None:
        raise _UNAUTHORIZED

    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    api_key = result.scalar_one_or_none()

    # Always call verify to prevent timing attacks even when key is not found
    if api_key is None:
        raise _UNAUTHORIZED

    if not verify_key(x_api_key, api_key.key_hash):
        raise _UNAUTHORIZED

    if api_key.expires_at is not None:
        expires_at = api_key.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at < datetime.now(UTC):
            raise _UNAUTHORIZED

    # Track last usage — committed here so read-only routes update it too
    api_key.last_used_at = datetime.now(UTC)
    await db.commit()

    result = await db.execute(select(Tenant).where(Tenant.id == api_key.tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise _UNAUTHORIZED

    return tenant  # type: ignore[return-value]


# Annotated shortcuts for use in route signatures:
#   async def route(tenant: TenantDep, db: DbDep, redis: RedisDep): ...
TenantDep = Annotated[Tenant, Depends(get_current_tenant)]
DbDep = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[Redis, Depends(get_redis)]
