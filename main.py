import asyncio
import contextlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from crewlayer.api.routes import actions, agents, auth, context, memory
from crewlayer.core.context.blackboard import cleanup_expired
from crewlayer.db.session import AsyncSessionLocal

_CLEANUP_INTERVAL = 60  # seconds


async def _cleanup_loop() -> None:
    """Background task: purge expired context entries every minute."""
    while True:
        await asyncio.sleep(_CLEANUP_INTERVAL)
        with contextlib.suppress(Exception):
            async with AsyncSessionLocal() as db:
                await cleanup_expired(db)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    task = asyncio.create_task(_cleanup_loop())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(
    title="CrewLayer",
    description="Open source backend for AI agents with persistent memory and multi-agent support",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/v1", tags=["auth"])
app.include_router(agents.router, prefix="/v1/agents", tags=["agents"])
app.include_router(memory.router, prefix="/v1", tags=["memory"])
app.include_router(actions.router, prefix="/v1", tags=["actions"])
app.include_router(context.router, prefix="/v1/context", tags=["context"])


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
