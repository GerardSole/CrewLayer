import asyncio
import contextlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from crewlayer.api.middleware.audit import AuditLogMiddleware
from crewlayer.api.middleware.ratelimit import check_rate_limit
from crewlayer.api.routes import actions, agents, audit, auth, context, memory, sessions, streaming, usage, webhooks
from crewlayer.core.context.blackboard import cleanup_expired
from crewlayer.core.memory.decay import decay_importance
from crewlayer.db.session import AsyncSessionLocal

_CLEANUP_INTERVAL = 60       # seconds
_DECAY_INTERVAL = 86_400     # 24 hours in seconds


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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    cleanup_task = asyncio.create_task(_cleanup_loop())
    decay_task = asyncio.create_task(_decay_loop())
    yield
    cleanup_task.cancel()
    decay_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await cleanup_task
    with contextlib.suppress(asyncio.CancelledError):
        await decay_task


app = FastAPI(
    title="CrewLayer",
    description="Open source backend for AI agents with persistent memory and multi-agent support",
    version="0.1.0",
    lifespan=lifespan,
    dependencies=[Depends(check_rate_limit)],
)

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


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
