import asyncio
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select

from crewlayer.api.deps import DbDep, RedisDep, TenantDep, check_scope
from crewlayer.core.memory.episodic import EpisodeNotFoundError, EpisodicMemory
from crewlayer.core.webhooks.dispatcher import dispatch
from crewlayer.db.models import Agent, Episode, EpisodeStatusEnum

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class EpisodeCreate(BaseModel):
    title: str
    description: str | None = None
    metadata: dict[str, Any] = {}


class EpisodeResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    agent_id: uuid.UUID
    title: str
    description: str | None = None
    status: EpisodeStatusEnum
    summary: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    metadata: dict[str, Any] = {}

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, obj: Any) -> "EpisodeResponse":
        return cls(
            id=obj.id,
            tenant_id=obj.tenant_id,
            agent_id=obj.agent_id,
            title=obj.title,
            description=obj.description,
            status=obj.status,
            summary=obj.summary,
            started_at=obj.started_at,
            completed_at=obj.completed_at,
            metadata=obj.metadata_,
        )


class MemorySummary(BaseModel):
    id: uuid.UUID
    content: str
    importance: float
    created_at: datetime


class SessionSummary(BaseModel):
    id: uuid.UUID
    status: str
    started_at: datetime
    closed_at: datetime | None = None
    message_count: int


class EpisodeDetailResponse(EpisodeResponse):
    sessions: list[SessionSummary] = []
    memories: list[MemorySummary] = []


class RecallRequest(BaseModel):
    query: str
    limit: int = 10
    min_similarity: float = 0.0


class RecallResult(BaseModel):
    memory_id: uuid.UUID
    content: str
    importance: float
    similarity: float


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_agent_or_404(agent_id: uuid.UUID, tenant_id: uuid.UUID, db: DbDep) -> Agent:
    result = await db.execute(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agente no encontrado")
    return agent


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post(
    "/agents/{agent_id}/episodes",
    status_code=status.HTTP_201_CREATED,
    response_model=EpisodeResponse,
    dependencies=[check_scope("agents:write")],
    summary="Create a new episode for an agent",
)
async def create_episode(
    agent_id: uuid.UUID,
    body: EpisodeCreate,
    tenant: TenantDep,
    db: DbDep,
) -> EpisodeResponse:
    """Create an active episode that groups related memories across sessions."""
    await _get_agent_or_404(agent_id, tenant.id, db)
    em = EpisodicMemory(db)
    episode = await em.create_episode(
        tenant_id=tenant.id,
        agent_id=agent_id,
        title=body.title,
        description=body.description,
        metadata=body.metadata,
    )
    await db.commit()
    await db.refresh(episode)
    return EpisodeResponse.from_orm(episode)


@router.get(
    "/agents/{agent_id}/episodes",
    response_model=list[EpisodeResponse],
    dependencies=[check_scope("agents:read")],
    summary="List episodes for an agent",
)
async def list_episodes(
    agent_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
    filter_status: Annotated[EpisodeStatusEnum | None, Query(alias="status")] = None,
) -> list[EpisodeResponse]:
    """List episodes for an agent, optionally filtered by status."""
    await _get_agent_or_404(agent_id, tenant.id, db)
    stmt = select(Episode).where(Episode.tenant_id == tenant.id, Episode.agent_id == agent_id)
    if filter_status is not None:
        stmt = stmt.where(Episode.status == filter_status)
    stmt = stmt.order_by(Episode.started_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [EpisodeResponse.from_orm(ep) for ep in rows]


@router.get(
    "/agents/{agent_id}/episodes/{episode_id}",
    response_model=EpisodeDetailResponse,
    dependencies=[check_scope("agents:read")],
    summary="Get episode detail with linked sessions and memories",
)
async def get_episode(
    agent_id: uuid.UUID,
    episode_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
) -> EpisodeDetailResponse:
    """Return full episode detail including associated sessions and memories."""
    await _get_agent_or_404(agent_id, tenant.id, db)
    em = EpisodicMemory(db)
    try:
        # Use the internal loader for consistent tenant isolation
        episode = await em._load_episode(episode_id, tenant.id)
    except EpisodeNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Episodio no encontrado")

    if episode.agent_id != agent_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Episodio no encontrado")

    sessions = await em.get_episode_sessions(episode_id)
    memories = await em.get_episode_memories(episode_id)

    return EpisodeDetailResponse(
        **EpisodeResponse.from_orm(episode).model_dump(),
        sessions=[
            SessionSummary(
                id=s.id,
                status=s.status.value,
                started_at=s.started_at,
                closed_at=s.closed_at,
                message_count=s.message_count,
            )
            for s in sessions
        ],
        memories=[
            MemorySummary(id=m.id, content=m.content, importance=m.importance, created_at=m.created_at)
            for m in memories
        ],
    )


@router.post(
    "/agents/{agent_id}/episodes/{episode_id}/complete",
    response_model=EpisodeResponse,
    dependencies=[check_scope("agents:write")],
    summary="Complete an episode and generate its AI summary",
)
async def complete_episode(
    agent_id: uuid.UUID,
    episode_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
) -> EpisodeResponse:
    """Mark an episode as completed and generate a summary via Claude."""
    await _get_agent_or_404(agent_id, tenant.id, db)
    em = EpisodicMemory(db)
    try:
        episode = await em.complete_episode(tenant.id, episode_id)
    except EpisodeNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Episodio no encontrado")
    if episode.agent_id != agent_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Episodio no encontrado")
    await db.commit()
    await db.refresh(episode)
    asyncio.create_task(
        dispatch(tenant.id, "episode.completed", {
            "agent_id": str(agent_id),
            "episode_id": str(episode_id),
            "summary": episode.summary,
        })
    )
    return EpisodeResponse.from_orm(episode)


@router.post(
    "/agents/{agent_id}/episodes/{episode_id}/recall",
    response_model=list[RecallResult],
    dependencies=[check_scope("memory:read")],
    summary="Semantic search within an episode's memories",
)
async def recall_episode(
    agent_id: uuid.UUID,
    episode_id: uuid.UUID,
    body: RecallRequest,
    tenant: TenantDep,
    db: DbDep,
    redis: RedisDep,
) -> list[RecallResult]:
    """Search memories associated with a specific episode using cosine similarity."""
    await _get_agent_or_404(agent_id, tenant.id, db)
    em = EpisodicMemory(db)
    try:
        episode = await em._load_episode(episode_id, tenant.id)
    except EpisodeNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Episodio no encontrado")
    if episode.agent_id != agent_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Episodio no encontrado")

    results = await em.recall_episode(
        tenant_id=tenant.id,
        episode_id=episode_id,
        query=body.query,
        limit=body.limit,
        min_similarity=body.min_similarity,
        redis=redis,
    )
    return [
        RecallResult(
            memory_id=mem.id,
            content=mem.content,
            importance=mem.importance,
            similarity=sim,
        )
        for mem, sim in results
    ]
