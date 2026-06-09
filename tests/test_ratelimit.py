"""Rate limiting tests: limit enforcement, headers, plan tiers, reset, embedding quota."""
import time
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.core.ratelimit.limiter import PLAN_LIMITS, SlidingWindowLimiter
from crewlayer.db.models import PlanEnum, Tenant

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _setup(client: AsyncClient) -> tuple[dict, dict, str]:
    """Create a tenant; return (tenant_json, headers, key_id_hex)."""
    r = await client.post("/v1/tenants", json={"name": f"RLCo-{uuid.uuid4()}"})
    assert r.status_code == 201
    tenant = r.json()
    raw_key: str = tenant["initial_api_key"]
    key_id_hex = raw_key.split("_")[1]
    return tenant, {"X-API-Key": raw_key}, key_id_hex


async def _set_plan(
    tenant_id: str,
    plan: PlanEnum,
    db: AsyncSession,
    redis: Redis,
    key_id_hex: str,
) -> None:
    """Upgrade/downgrade a tenant's plan and invalidate the rl_meta cache."""
    await db.execute(
        update(Tenant).where(Tenant.id == uuid.UUID(tenant_id)).values(plan=plan)
    )
    await db.commit()
    # Bust the rate-limit metadata cache so the middleware re-reads from DB
    await redis.delete(f"rl_meta:{key_id_hex}")


async def _fill_window(redis: Redis, tenant_id: str, window_key: str, count: int) -> None:
    """Pre-fill a sliding-window ZSET with *count* fake entries at the current timestamp."""
    key = f"rl:{window_key}:{tenant_id}"
    now_ms = int(time.time() * 1000)
    mapping = {f"fake-{i}": float(now_ms - i) for i in range(count)}
    await redis.zadd(key, mapping)


# ---------------------------------------------------------------------------
# Headers on normal requests
# ---------------------------------------------------------------------------

async def test_rate_limit_headers_present_on_authenticated_request(
    client: AsyncClient,
    redis_client: Redis,
) -> None:
    _, headers, _ = await _setup(client)

    r = await client.get("/v1/agents", headers=headers)

    assert r.status_code == 200
    assert "x-ratelimit-limit" in r.headers
    assert "x-ratelimit-remaining" in r.headers
    assert "x-ratelimit-reset" in r.headers


async def test_rate_limit_headers_match_free_plan_minute_limit(
    client: AsyncClient,
    redis_client: Redis,
) -> None:
    _, headers, _ = await _setup(client)
    free_limit = PLAN_LIMITS[PlanEnum.free]
    assert free_limit is not None

    r = await client.get("/v1/agents", headers=headers)

    assert r.headers["x-ratelimit-limit"] == str(free_limit.per_minute)


async def test_unauthenticated_request_has_no_rl_headers(client: AsyncClient) -> None:
    r = await client.get("/health")

    assert "x-ratelimit-limit" not in r.headers


# ---------------------------------------------------------------------------
# Minute limit enforcement
# ---------------------------------------------------------------------------

async def test_minute_limit_exceeded_returns_429(
    client: AsyncClient,
    redis_client: Redis,
) -> None:
    tenant, headers, _ = await _setup(client)
    free_limit = PLAN_LIMITS[PlanEnum.free]
    assert free_limit is not None

    # Pre-fill exactly at the minute limit so the next request tips it over
    await _fill_window(redis_client, tenant["id"], "min", free_limit.per_minute)

    r = await client.get("/v1/agents", headers=headers)

    assert r.status_code == 429
    body = r.json()
    assert body["detail"]["error"] == "rate_limit_exceeded"
    assert "reset_at" in body["detail"]


async def test_429_includes_rl_headers(
    client: AsyncClient,
    redis_client: Redis,
) -> None:
    tenant, headers, _ = await _setup(client)
    free_limit = PLAN_LIMITS[PlanEnum.free]
    assert free_limit is not None

    await _fill_window(redis_client, tenant["id"], "min", free_limit.per_minute)

    r = await client.get("/v1/agents", headers=headers)

    assert r.status_code == 429
    assert "x-ratelimit-limit" in r.headers
    assert r.headers["x-ratelimit-remaining"] == "0"
    assert "x-ratelimit-reset" in r.headers


# ---------------------------------------------------------------------------
# Day limit enforcement
# ---------------------------------------------------------------------------

async def test_day_limit_exceeded_returns_429(
    client: AsyncClient,
    redis_client: Redis,
) -> None:
    tenant, headers, _ = await _setup(client)
    free_limit = PLAN_LIMITS[PlanEnum.free]
    assert free_limit is not None

    await _fill_window(redis_client, tenant["id"], "day", free_limit.per_day)

    r = await client.get("/v1/agents", headers=headers)

    assert r.status_code == 429


# ---------------------------------------------------------------------------
# Remaining count decrements correctly
# ---------------------------------------------------------------------------

async def test_remaining_decrements_on_each_request(
    client: AsyncClient,
    redis_client: Redis,
) -> None:
    _, headers, _ = await _setup(client)

    r1 = await client.get("/v1/agents", headers=headers)
    r2 = await client.get("/v1/agents", headers=headers)

    rem1 = int(r1.headers["x-ratelimit-remaining"])
    rem2 = int(r2.headers["x-ratelimit-remaining"])
    assert rem2 == rem1 - 1


# ---------------------------------------------------------------------------
# Reset: old entries slide out of the window
# ---------------------------------------------------------------------------

async def test_limit_resets_after_window_expires(
    client: AsyncClient,
    redis_client: Redis,
) -> None:
    tenant, headers, _ = await _setup(client)
    free_limit = PLAN_LIMITS[PlanEnum.free]
    assert free_limit is not None

    # Fill with entries that are just inside the window edge (recent)
    now_ms = int(time.time() * 1000)
    key = f"rl:min:{tenant['id']}"
    # Add entries timestamped 65 seconds ago — already outside the 60 s window
    old_ms = now_ms - 65_000
    mapping = {f"old-{i}": float(old_ms - i) for i in range(free_limit.per_minute)}
    await redis_client.zadd(key, mapping)

    # These old entries should be evicted by the Lua script; request must succeed
    r = await client.get("/v1/agents", headers=headers)

    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Plan tiers: pro gets a higher limit
# ---------------------------------------------------------------------------

async def test_pro_plan_has_higher_minute_limit(
    client: AsyncClient,
    db: AsyncSession,
    redis_client: Redis,
) -> None:
    tenant, headers, key_id_hex = await _setup(client)
    await _set_plan(tenant["id"], PlanEnum.pro, db, redis_client, key_id_hex)
    pro_limit = PLAN_LIMITS[PlanEnum.pro]
    assert pro_limit is not None

    # Fill to free-plan limit (100) — a pro tenant should still be under their limit
    free_limit = PLAN_LIMITS[PlanEnum.free]
    assert free_limit is not None
    await _fill_window(redis_client, tenant["id"], "min", free_limit.per_minute)

    r = await client.get("/v1/agents", headers=headers)

    assert r.status_code == 200
    assert r.headers["x-ratelimit-limit"] == str(pro_limit.per_minute)


# ---------------------------------------------------------------------------
# Enterprise plan: unlimited
# ---------------------------------------------------------------------------

async def test_enterprise_plan_bypasses_limits(
    client: AsyncClient,
    db: AsyncSession,
    redis_client: Redis,
) -> None:
    tenant, headers, key_id_hex = await _setup(client)
    await _set_plan(tenant["id"], PlanEnum.enterprise, db, redis_client, key_id_hex)

    # Fill WAY over any plan's minute limit
    await _fill_window(redis_client, tenant["id"], "min", 5_000)

    r = await client.get("/v1/agents", headers=headers)

    assert r.status_code == 200
    assert r.headers.get("x-ratelimit-limit") == "unlimited"


# ---------------------------------------------------------------------------
# Embedding endpoint quota (20 req/min on free)
# ---------------------------------------------------------------------------

async def test_embedding_endpoint_has_separate_quota(
    client: AsyncClient,
    redis_client: Redis,
) -> None:
    tenant, headers, _ = await _setup(client)
    free_limit = PLAN_LIMITS[PlanEnum.free]
    assert free_limit is not None

    # Create an agent so we can call memory endpoints
    r = await client.post("/v1/agents", json={"name": "emb-bot"}, headers=headers)
    assert r.status_code == 201
    agent_id = r.json()["id"]

    # Fill only the embedding bucket to its limit — general bucket untouched
    await _fill_window(redis_client, tenant["id"], "emb", free_limit.embedding_per_minute)

    # POST to /memory/recall should hit the embedding quota
    r = await client.post(
        f"/v1/agents/{agent_id}/memory/recall",
        json={"query": "test", "limit": 5},
        headers=headers,
    )

    assert r.status_code == 429
    assert r.json()["detail"]["error"] == "rate_limit_exceeded"


async def test_non_embedding_endpoint_not_affected_by_embedding_quota(
    client: AsyncClient,
    redis_client: Redis,
) -> None:
    tenant, headers, _ = await _setup(client)
    free_limit = PLAN_LIMITS[PlanEnum.free]
    assert free_limit is not None

    # Fill only the embedding bucket
    await _fill_window(redis_client, tenant["id"], "emb", free_limit.embedding_per_minute)

    # A non-embedding endpoint (GET /agents) should pass through normally
    r = await client.get("/v1/agents", headers=headers)

    assert r.status_code == 200


# ---------------------------------------------------------------------------
# /v1/usage endpoint
# ---------------------------------------------------------------------------

async def test_usage_endpoint_structure_and_free_limits(
    client: AsyncClient,
    redis_client: Redis,
) -> None:
    """Verifies response shape, plan label, and that limits match the free-plan config."""
    _, headers, _ = await _setup(client)

    r = await client.get("/v1/usage", headers=headers)

    assert r.status_code == 200
    data = r.json()
    assert data["plan"] == "free"
    # The GET /v1/usage request itself is counted in the middleware before the
    # handler reads usage, so counts are >= 1, not necessarily 0.
    assert data["usage"]["requests_today"] >= 1
    assert data["usage"]["requests_this_minute"] >= 1
    free_limit = PLAN_LIMITS[PlanEnum.free]
    assert free_limit is not None
    assert data["limits"]["per_minute"] == free_limit.per_minute
    assert data["limits"]["per_day"] == free_limit.per_day


async def test_usage_endpoint_reflects_request_counts(
    client: AsyncClient,
    redis_client: Redis,
) -> None:
    tenant, headers, _ = await _setup(client)

    await _fill_window(redis_client, tenant["id"], "day", 42)
    await _fill_window(redis_client, tenant["id"], "min", 7)

    r = await client.get("/v1/usage", headers=headers)

    assert r.status_code == 200
    data = r.json()
    # The /usage request itself adds 1 to the minute counter, so we get 8+
    assert data["usage"]["requests_today"] >= 42
    assert data["usage"]["requests_this_minute"] >= 7


async def test_usage_enterprise_shows_null_limits(
    client: AsyncClient,
    db: AsyncSession,
    redis_client: Redis,
) -> None:
    tenant, headers, key_id_hex = await _setup(client)
    await _set_plan(tenant["id"], PlanEnum.enterprise, db, redis_client, key_id_hex)

    r = await client.get("/v1/usage", headers=headers)

    assert r.status_code == 200
    data = r.json()
    assert data["plan"] == "enterprise"
    assert data["limits"]["per_minute"] is None
    assert data["limits"]["per_day"] is None


# ---------------------------------------------------------------------------
# Tenant isolation: one tenant's counter doesn't bleed into another
# ---------------------------------------------------------------------------

async def test_rate_limit_tenant_isolation(
    client: AsyncClient,
    redis_client: Redis,
) -> None:
    tenant_a, headers_a, _ = await _setup(client)
    tenant_b, headers_b, _ = await _setup(client)
    free_limit = PLAN_LIMITS[PlanEnum.free]
    assert free_limit is not None

    # Exhaust tenant A
    await _fill_window(redis_client, tenant_a["id"], "min", free_limit.per_minute)

    r_a = await client.get("/v1/agents", headers=headers_a)
    r_b = await client.get("/v1/agents", headers=headers_b)

    assert r_a.status_code == 429
    assert r_b.status_code == 200
