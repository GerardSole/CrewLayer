import time
import uuid
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis

from crewlayer.db.models import PlanEnum

# Window sizes in milliseconds
WINDOW_MINUTE_MS: int = 60_000
WINDOW_DAY_MS: int = 86_400_000


@dataclass(frozen=True)
class PlanLimits:
    per_minute: int
    per_day: int
    embedding_per_minute: int


# None means unlimited (enterprise)
PLAN_LIMITS: dict[PlanEnum, PlanLimits | None] = {
    PlanEnum.free: PlanLimits(
        per_minute=100,
        per_day=10_000,
        embedding_per_minute=20,
    ),
    PlanEnum.pro: PlanLimits(
        per_minute=1_000,
        per_day=500_000,
        embedding_per_minute=200,
    ),
    PlanEnum.enterprise: None,
}


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_at_ms: int  # Unix timestamp in milliseconds


# Atomic Lua script: remove stale entries, check count, conditionally add new entry.
# Returns [allowed(0/1), count_after_op, reset_at_ms]
_SLIDING_WINDOW_LUA = """
local key      = KEYS[1]
local now_ms   = tonumber(ARGV[1])
local win_ms   = tonumber(ARGV[2])
local lim      = tonumber(ARGV[3])
local jti      = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, '-inf', now_ms - win_ms)

local cnt = tonumber(redis.call('ZCARD', key))

if cnt >= lim then
    local oldest = redis.call('ZRANGE', key, 0, 0)
    local oldest_score
    if #oldest > 0 then
        oldest_score = tonumber(redis.call('ZSCORE', key, oldest[1]))
    else
        oldest_score = now_ms
    end
    return {0, cnt, oldest_score + win_ms}
else
    redis.call('ZADD', key, now_ms, jti)
    redis.call('PEXPIRE', key, win_ms + 1000)
    return {1, cnt + 1, now_ms + win_ms}
end
"""


class SlidingWindowLimiter:
    """Per-tenant sliding-window rate limiter backed by Redis sorted sets."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._script = redis.register_script(_SLIDING_WINDOW_LUA)

    async def check(
        self,
        tenant_id: uuid.UUID,
        window_key: str,
        window_ms: int,
        limit: int,
    ) -> RateLimitResult:
        """Atomically check and record one request. Returns the result.

        window_key: short suffix used in the Redis key, e.g. "min", "day", "emb".
        """
        key = f"rl:{window_key}:{tenant_id}"
        now_ms = int(time.time() * 1000)
        jti = f"{now_ms}-{uuid.uuid4().hex[:8]}"

        raw: list[Any] = await self._script(
            keys=[key],
            args=[str(now_ms), str(window_ms), str(limit), jti],
        )

        allowed = bool(int(raw[0]))
        count = int(raw[1])
        reset_at_ms = int(raw[2])

        return RateLimitResult(
            allowed=allowed,
            limit=limit,
            remaining=max(0, limit - count),
            reset_at_ms=reset_at_ms,
        )

    async def get_usage(self, tenant_id: uuid.UUID) -> dict[str, int]:
        """Return live request counts across the three tracked windows."""
        now_ms = int(time.time() * 1000)
        pipe = self._redis.pipeline()
        windows = [
            (f"rl:day:{tenant_id}", WINDOW_DAY_MS),
            (f"rl:min:{tenant_id}", WINDOW_MINUTE_MS),
            (f"rl:emb:{tenant_id}", WINDOW_MINUTE_MS),
        ]
        for key, win_ms in windows:
            pipe.zremrangebyscore(key, "-inf", now_ms - win_ms)
            pipe.zcard(key)
        results: list[Any] = await pipe.execute()
        return {
            "requests_today": int(results[1]),
            "requests_this_minute": int(results[3]),
            "embedding_requests_this_minute": int(results[5]),
        }
