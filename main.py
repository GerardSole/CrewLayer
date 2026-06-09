from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from crewlayer.api.routes import agents, memory, actions, context, auth


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield


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
app.include_router(memory.router, prefix="/v1/memory", tags=["memory"])
app.include_router(actions.router, prefix="/v1/actions", tags=["actions"])
app.include_router(context.router, prefix="/v1/context", tags=["context"])


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
