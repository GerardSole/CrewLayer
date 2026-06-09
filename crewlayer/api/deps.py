import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Request, status
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

_FORBIDDEN = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="Scope insuficiente para esta operación",
)


def _parse_key_id(raw_key: str) -> uuid.UUID | None:
    """Extract the key's UUID from 'crwl_{uuid32hex}_{secret}' format."""
    parts = raw_key.split("_", 2)
    if len(parts) != 3 or parts[0] != "crwl":
        return None
    try:
        return uuid.UUID(parts[1])
    except ValueError:
        return None


@dataclass
class _AuthContext:
    tenant: Tenant
    api_key: ApiKey


async def _get_auth(
    db: AsyncSession = Depends(get_db),
    x_api_key: Annotated[str | None, Header()] = None,
) -> _AuthContext:
    """Validate X-API-Key and return both Tenant and ApiKey.

    FastAPI caches this per request, so TenantDep and ApiKeyDep share one DB round-trip.
    """
    if x_api_key is None:
        raise _UNAUTHORIZED

    key_id = _parse_key_id(x_api_key)
    if key_id is None:
        raise _UNAUTHORIZED

    key_result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    api_key: ApiKey | None = key_result.scalar_one_or_none()

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

    api_key.last_used_at = datetime.now(UTC)
    await db.commit()

    tenant_result = await db.execute(select(Tenant).where(Tenant.id == api_key.tenant_id))
    tenant: Tenant | None = tenant_result.scalar_one_or_none()
    if tenant is None:
        raise _UNAUTHORIZED

    return _AuthContext(tenant=tenant, api_key=api_key)


async def get_current_tenant(auth: _AuthContext = Depends(_get_auth)) -> Tenant:
    return auth.tenant


async def get_current_api_key(auth: _AuthContext = Depends(_get_auth)) -> ApiKey:
    return auth.api_key


def check_scope(required_scope: str) -> Any:
    """Return a FastAPI dependency that enforces a scope and optional agent_ids restriction.

    Semantics:
    - Empty scopes list on the key → full access (backward-compatible bootstrap keys).
    - Non-empty scopes → only the listed scopes are permitted; anything else → 403.
    - Non-empty agent_ids → the key may only operate on those specific agents;
      routes with an {agent_id} path parameter are checked; routes without one are unrestricted.
    """
    async def _dep(
        request: Request,
        api_key: ApiKey = Depends(get_current_api_key),
    ) -> None:
        # Scope check: empty = full access
        if api_key.scopes and required_scope not in api_key.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Scope requerido: '{required_scope}'",
            )

        # Agent restriction check
        if api_key.agent_ids:
            agent_id_str = request.path_params.get("agent_id")
            if agent_id_str:
                try:
                    agent_id = uuid.UUID(str(agent_id_str))
                except ValueError:
                    pass
                else:
                    if agent_id not in api_key.agent_ids:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Esta API key no tiene acceso a este agente",
                        )

    return Depends(_dep)


# Annotated shortcuts for use in route signatures:
#   async def route(tenant: TenantDep, db: DbDep, redis: RedisDep): ...
TenantDep = Annotated[Tenant, Depends(get_current_tenant)]
ApiKeyDep = Annotated[ApiKey, Depends(get_current_api_key)]
DbDep = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[Redis, Depends(get_redis)]
