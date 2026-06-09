from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from crewlayer.api.deps import RedisDep, TenantDep
from crewlayer.core.ratelimit.limiter import PLAN_LIMITS, SlidingWindowLimiter

router = APIRouter()


class LimitsInfo(BaseModel):
    per_minute: int | None
    per_day: int | None
    embedding_per_minute: int | None


class UsageStats(BaseModel):
    requests_today: int
    requests_this_minute: int
    embedding_requests_this_minute: int


class UsageResponse(BaseModel):
    tenant_id: str
    plan: str
    usage: UsageStats
    limits: LimitsInfo
    timestamp: str


@router.get("/usage", response_model=UsageResponse)
async def get_usage(tenant: TenantDep, redis: RedisDep) -> UsageResponse:
    """Return the tenant's live API consumption against their plan's quotas."""
    limiter = SlidingWindowLimiter(redis)
    raw_usage = await limiter.get_usage(tenant.id)

    plan_limits = PLAN_LIMITS[tenant.plan]
    if plan_limits is None:
        limits_info = LimitsInfo(
            per_minute=None,
            per_day=None,
            embedding_per_minute=None,
        )
    else:
        limits_info = LimitsInfo(
            per_minute=plan_limits.per_minute,
            per_day=plan_limits.per_day,
            embedding_per_minute=plan_limits.embedding_per_minute,
        )

    return UsageResponse(
        tenant_id=str(tenant.id),
        plan=tenant.plan.value,
        usage=UsageStats(**raw_usage),
        limits=limits_info,
        timestamp=datetime.now(UTC).isoformat(),
    )
