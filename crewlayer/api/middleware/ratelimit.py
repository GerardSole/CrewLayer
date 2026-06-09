"""Rate-limit middleware implemented as a FastAPI global dependency.

Runs before every route handler. Skips requests without an API key (they
will fail at route-level auth anyway). For authenticated requests it:

  1. Parses the key UUID from the X-API-Key header (no bcrypt required).
  2. Resolves tenant_id + plan from a short-lived Redis cache (or DB on miss).
  3. Enforces per-minute, per-day, and (for embedding endpoints) per-minute
     embedding limits using a sliding-window sorted-set algorithm.
  4. Adds X-RateLimit-* headers to every passing response.
  5. Raises HTTP 429 with {"error": "rate_limit_exceeded", "reset_at": "..."}.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.api.deps import DbDep, RedisDep
from crewlayer.core.ratelimit.limiter import (
    PLAN_LIMITS,
    WINDOW_DAY_MS,
    WINDOW_MINUTE_MS,
    RateLimitResult,
    SlidingWindowLimiter,
)
from crewlayer.db.models import ApiKey, PlanEnum, Tenant

# Redis TTL (seconds) for key_id → (tenant_id, plan) cache entries
_META_TTL = 300

# Endpoint path suffixes that incur the extra embedding quota
_EMBEDDING_SUFFIXES = ("/memory/recall", "/memory/extract")


def _parse_key_id(raw_key: str) -> str | None:
    """Return the UUID hex from crwl_{hex}_{secret} without touching bcrypt."""
    parts = raw_key.split("_", 2)
    if len(parts) != 3 or parts[0] != "crwl":
        return None
    return parts[1]


def _is_embedding_path(path: str) -> bool:
    return any(path.endswith(s) for s in _EMBEDDING_SUFFIXES)


async def _resolve_tenant(
    key_id_hex: str,
    redis: object,
    db: AsyncSession,
) -> tuple[uuid.UUID, PlanEnum] | None:
    """Return (tenant_id, plan) from Redis cache, falling back to DB on miss."""
    from redis.asyncio import Redis as _Redis  # local import avoids cycle

    r: _Redis = redis  # type: ignore[assignment]

    cache_key = f"rl_meta:{key_id_hex}"
    cached: str | None = await r.get(cache_key)  # type: ignore[assignment]
    if cached:
        tid_str, plan_str = cached.split(":", 1)
        return uuid.UUID(tid_str), PlanEnum(plan_str)

    try:
        key_uuid = uuid.UUID(key_id_hex)
    except ValueError:
        return None

    row = (
        await db.execute(
            select(ApiKey.tenant_id, Tenant.plan)
            .join(Tenant, Tenant.id == ApiKey.tenant_id)
            .where(ApiKey.id == key_uuid)
        )
    ).first()
    if row is None:
        return None

    tenant_id, plan = row
    await r.set(cache_key, f"{tenant_id}:{plan.value}", ex=_META_TTL)
    return tenant_id, plan


def _raise_429(result: RateLimitResult) -> None:
    reset_iso = datetime.fromtimestamp(result.reset_at_ms / 1000, UTC).isoformat()
    reset_epoch = result.reset_at_ms // 1000
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={"error": "rate_limit_exceeded", "reset_at": reset_iso},
        headers={
            "X-RateLimit-Limit": str(result.limit),
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(reset_epoch),
        },
    )


async def check_rate_limit(
    request: Request,
    response: Response,
    redis: RedisDep,
    db: DbDep,
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    """FastAPI global dependency that enforces per-tenant rate limits."""
    if x_api_key is None:
        return

    key_id_hex = _parse_key_id(x_api_key)
    if key_id_hex is None:
        return

    resolved = await _resolve_tenant(key_id_hex, redis, db)
    if resolved is None:
        # Unknown key — the route's TenantDep will return 401.
        return

    tenant_id, plan = resolved
    limits = PLAN_LIMITS[plan]

    if limits is None:
        # Enterprise: unlimited
        response.headers["X-RateLimit-Limit"] = "unlimited"
        response.headers["X-RateLimit-Remaining"] = "unlimited"
        response.headers["X-RateLimit-Reset"] = "0"
        return

    limiter = SlidingWindowLimiter(redis)

    # Per-minute check
    min_result = await limiter.check(tenant_id, "min", WINDOW_MINUTE_MS, limits.per_minute)
    if not min_result.allowed:
        _raise_429(min_result)

    # Per-day check
    day_result = await limiter.check(tenant_id, "day", WINDOW_DAY_MS, limits.per_day)
    if not day_result.allowed:
        _raise_429(day_result)

    # Embedding-specific per-minute check
    if _is_embedding_path(request.url.path):
        emb_result = await limiter.check(tenant_id, "emb", WINDOW_MINUTE_MS, limits.embedding_per_minute)
        if not emb_result.allowed:
            _raise_429(emb_result)

    # Headers reflect the per-minute window (most restrictive on short bursts)
    reset_epoch = min_result.reset_at_ms // 1000
    response.headers["X-RateLimit-Limit"] = str(limits.per_minute)
    response.headers["X-RateLimit-Remaining"] = str(min_result.remaining)
    response.headers["X-RateLimit-Reset"] = str(reset_epoch)
