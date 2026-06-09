import asyncio
import contextlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from crewlayer.api.middleware.audit import AuditLogMiddleware
from crewlayer.api.middleware.ratelimit import check_rate_limit
from crewlayer.api.routes import (
    actions,
    agents,
    audit,
    auth,
    context,
    memory,
    metrics as metrics_route,
    sessions,
    streaming,
    usage,
    webhooks,
)
from crewlayer.core.config import settings
from crewlayer.core.context.blackboard import cleanup_expired
from crewlayer.core.memory.decay import decay_importance
from crewlayer.core.metrics.collectors import collect_metrics
from crewlayer.core.streaming.context_broker import ContextBroker
from crewlayer.db.session import AsyncSessionLocal

_CLEANUP_INTERVAL = 60       # seconds
_DECAY_INTERVAL = 86_400     # 24 hours in seconds
_METRICS_INTERVAL = 60       # seconds


async def _cleanup_loop() -> None:
    """Background task: purge expired context entries every minute."""
    while True:
        await asyncio.sleep(_CLEANUP_INTERVAL)
        with contextlib.suppress(Exception):
            async with AsyncSessionLocal() as db:
                await cleanup_expired(db)


async def _decay_loop() -> None:
    """Background task: decay importance of stale memories every 24 hours."""
    while True:
        await asyncio.sleep(_DECAY_INTERVAL)
        with contextlib.suppress(Exception):
            async with AsyncSessionLocal() as db:
                await decay_importance(db)
                await db.commit()


async def _metrics_loop() -> None:
    """Background task: refresh custom Prometheus gauges every 60 s."""
    while True:
        await collect_metrics()
        await asyncio.sleep(_METRICS_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Dedicated Redis connection for the context pub/sub broker
    broker_redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    app.state.context_broker = ContextBroker(broker_redis)

    cleanup_task = asyncio.create_task(_cleanup_loop())
    decay_task = asyncio.create_task(_decay_loop())
    metrics_task = asyncio.create_task(_metrics_loop())

    yield

    cleanup_task.cancel()
    decay_task.cancel()
    metrics_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await cleanup_task
    with contextlib.suppress(asyncio.CancelledError):
        await decay_task
    with contextlib.suppress(asyncio.CancelledError):
        await metrics_task

    await app.state.context_broker.aclose()
    with contextlib.suppress(Exception):
        await broker_redis.aclose()


app = FastAPI(
    title="CrewLayer",
    description="Open source backend for AI agents with persistent memory and multi-agent support",
    version="0.1.0",
    lifespan=lifespan,
    dependencies=[Depends(check_rate_limit)],
)

# Instrument HTTP request metrics — exclude /metrics and /health from tracking
Instrumentator(
    excluded_handlers=["/metrics", "/health"],
    should_ignore_untemplated=True,
).instrument(app)
# Note: .expose() is NOT called — /metrics is handled below with auth

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuditLogMiddleware)

app.include_router(auth.router, prefix="/v1", tags=["auth"])
app.include_router(agents.router, prefix="/v1/agents", tags=["agents"])
app.include_router(memory.router, prefix="/v1", tags=["memory"])
app.include_router(actions.router, prefix="/v1", tags=["actions"])
app.include_router(context.router, prefix="/v1/context", tags=["context"])
app.include_router(webhooks.router, prefix="/v1", tags=["webhooks"])
app.include_router(sessions.router, prefix="/v1", tags=["sessions"])
app.include_router(streaming.router, prefix="/v1", tags=["streaming"])
app.include_router(usage.router, prefix="/v1", tags=["usage"])
app.include_router(audit.router, prefix="/v1", tags=["audit"])
app.include_router(metrics_route.router, tags=["observability"])


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
