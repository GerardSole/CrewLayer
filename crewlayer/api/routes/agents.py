import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import String, cast, func, select, text
from sqlalchemy.dialects.postgresql import ARRAY

from crewlayer.api.deps import DbDep, RedisDep, TenantDep, check_scope
from crewlayer.core.agents.status import (
    apply_status,
    cache_status,
    read_cached_status,
)
from crewlayer.db.models import Agent, AgentStatusEnum

router = APIRouter()


class AgentCreate(BaseModel):
    name: str
    description: str | None = None
    config: dict[str, Any] = {}
    tags: list[str] = []


class AgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    config: dict[str, Any] | None = None
    tags: list[str] | None = None


class AgentResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: str | None = None
    config: dict[str, Any]
    status: AgentStatusEnum
    current_session_id: uuid.UUID | None = None
    status_updated_at: datetime
    tags: list[str] = []

    model_config = {"from_attributes": True}


class AgentStatusUpdate(BaseModel):
    status: AgentStatusEnum
    session_id: uuid.UUID | None = None


class AgentStatusResponse(BaseModel):
    agent_id: uuid.UUID
    status: AgentStatusEnum
    current_session_id: uuid.UUID | None = None
    updated_at: datetime


class TagCount(BaseModel):
    tag: str
    count: int


class TagsAddBody(BaseModel):
    tags: list[str]


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
# Tag endpoints — registered before /{agent_id} to avoid routing conflicts
# ---------------------------------------------------------------------------

@router.get(
    "/tags",
    response_model=list[TagCount],
    dependencies=[check_scope("agents:read")],
    summary="List all unique tags used by the tenant with per-tag counts",
)
async def list_tags(tenant: TenantDep, db: DbDep) -> list[TagCount]:
    """Return every distinct tag used by any agent of this tenant, with how many agents carry it."""
    stmt = (
        select(
            func.unnest(Agent.tags).label("tag"),
            func.count().label("count"),
        )
        .where(Agent.tenant_id == tenant.id)
        .group_by(text("tag"))
        .order_by(text("tag"))
    )
    rows = (await db.execute(stmt)).all()
    return [TagCount(tag=str(r.tag), count=int(r.count)) for r in rows]


# ---------------------------------------------------------------------------
# Agent CRUD
# ---------------------------------------------------------------------------

@router.post("", status_code=status.HTTP_201_CREATED, response_model=AgentResponse)
async def create_agent(body: AgentCreate, tenant: TenantDep, db: DbDep) -> AgentResponse:
    """Create a new agent for the authenticated tenant."""
    agent = Agent(
        tenant_id=tenant.id,
        name=body.name,
        description=body.description,
        config=body.config,
        tags=list(dict.fromkeys(body.tags)),  # deduplicate, preserve order
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return AgentResponse.model_validate(agent)


@router.get("", response_model=list[AgentResponse], dependencies=[check_scope("agents:read")])
async def list_agents(
    tenant: TenantDep,
    db: DbDep,
    filter_status: Annotated[AgentStatusEnum | None, Query(alias="status")] = None,
    tags: Annotated[str | None, Query(description="Comma-separated tags (AND logic)")] = None,
) -> list[AgentResponse]:
    """List agents for the authenticated tenant with optional status and tag filters.

    ``?tags=produccion,ventas`` returns only agents that have **all** the listed tags.
    """
    stmt = select(Agent).where(Agent.tenant_id == tenant.id)
    if filter_status is not None:
        stmt = stmt.where(Agent.status == filter_status)
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        if tag_list:
            # PostgreSQL: tags @> ARRAY['tag1','tag2'] — all listed tags must be present
            stmt = stmt.where(Agent.tags.contains(cast(tag_list, ARRAY(String))))
    rows = (await db.execute(stmt)).scalars().all()
    return [AgentResponse.model_validate(a) for a in rows]


@router.get("/{agent_id}", response_model=AgentResponse, dependencies=[check_scope("agents:read")])
async def get_agent(agent_id: uuid.UUID, tenant: TenantDep, db: DbDep) -> AgentResponse:
    """Get a single agent by ID."""
    return AgentResponse.model_validate(await _get_agent_or_404(agent_id, tenant.id, db))


@router.patch(
    "/{agent_id}",
    response_model=AgentResponse,
    dependencies=[check_scope("agents:write")],
    summary="Update agent name, description, config and/or tags",
)
async def update_agent(
    agent_id: uuid.UUID,
    body: AgentUpdate,
    tenant: TenantDep,
    db: DbDep,
) -> AgentResponse:
    """Partial update of an agent. Only fields present in the request body are changed."""
    agent = await _get_agent_or_404(agent_id, tenant.id, db)
    if body.name is not None:
        agent.name = body.name
    if body.description is not None:
        agent.description = body.description
    if body.config is not None:
        agent.config = body.config
    if body.tags is not None:
        agent.tags = list(dict.fromkeys(body.tags))
    await db.commit()
    await db.refresh(agent)
    return AgentResponse.model_validate(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: uuid.UUID, tenant: TenantDep, db: DbDep) -> None:
    """Delete an agent and all its associated data (cascade)."""
    agent = await _get_agent_or_404(agent_id, tenant.id, db)
    await db.delete(agent)
    await db.commit()


# ---------------------------------------------------------------------------
# Tag management endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/{agent_id}/tags",
    response_model=AgentResponse,
    dependencies=[check_scope("agents:write")],
    summary="Add tags to an agent without replacing existing ones",
)
async def add_tags(
    agent_id: uuid.UUID,
    body: TagsAddBody,
    tenant: TenantDep,
    db: DbDep,
) -> AgentResponse:
    """Append new tags to an agent. Existing tags are preserved; duplicates are ignored."""
    agent = await _get_agent_or_404(agent_id, tenant.id, db)
    current = list(agent.tags or [])
    existing_set = set(current)
    for t in body.tags:
        t = t.strip()
        if t and t not in existing_set:
            current.append(t)
            existing_set.add(t)
    agent.tags = current
    await db.commit()
    await db.refresh(agent)
    return AgentResponse.model_validate(agent)


@router.delete(
    "/{agent_id}/tags/{tag}",
    response_model=AgentResponse,
    dependencies=[check_scope("agents:write")],
    summary="Remove a single tag from an agent",
)
async def remove_tag(
    agent_id: uuid.UUID,
    tag: str,
    tenant: TenantDep,
    db: DbDep,
) -> AgentResponse:
    """Remove one tag from an agent. Returns 404 if the agent doesn't have that tag."""
    agent = await _get_agent_or_404(agent_id, tenant.id, db)
    current = list(agent.tags or [])
    if tag not in current:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tag '{tag}' no encontrado en este agente")
    agent.tags = [t for t in current if t != tag]
    await db.commit()
    await db.refresh(agent)
    return AgentResponse.model_validate(agent)


# ---------------------------------------------------------------------------
# Status endpoints
# ---------------------------------------------------------------------------

@router.patch(
    "/{agent_id}/status",
    response_model=AgentStatusResponse,
    dependencies=[check_scope("agents:write")],
)
async def update_agent_status(
    agent_id: uuid.UUID,
    body: AgentStatusUpdate,
    tenant: TenantDep,
    db: DbDep,
    redis: RedisDep,
) -> AgentStatusResponse:
    """Update the runtime status of an agent (idle / working / error)."""
    agent = await _get_agent_or_404(agent_id, tenant.id, db)
    apply_status(agent, body.status, body.session_id)
    await db.commit()
    await db.refresh(agent)
    await cache_status(agent.id, agent.status, agent.current_session_id, agent.status_updated_at, redis)
    return AgentStatusResponse(
        agent_id=agent.id,
        status=agent.status,
        current_session_id=agent.current_session_id,
        updated_at=agent.status_updated_at,
    )


@router.get(
    "/{agent_id}/status",
    response_model=AgentStatusResponse,
    dependencies=[check_scope("agents:read")],
)
async def get_agent_status(
    agent_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
    redis: RedisDep,
) -> AgentStatusResponse:
    """Get the current status of an agent. Served from Redis cache when available."""
    cached = await read_cached_status(agent_id, redis)
    if cached is not None:
        raw_sid = cached.get("current_session_id")
        return AgentStatusResponse(
            agent_id=agent_id,
            status=AgentStatusEnum(str(cached["status"])),
            current_session_id=uuid.UUID(str(raw_sid)) if raw_sid else None,
            updated_at=datetime.fromisoformat(str(cached["updated_at"])),
        )

    agent = await _get_agent_or_404(agent_id, tenant.id, db)
    await cache_status(agent.id, agent.status, agent.current_session_id, agent.status_updated_at, redis)
    return AgentStatusResponse(
        agent_id=agent.id,
        status=agent.status,
        current_session_id=agent.current_session_id,
        updated_at=agent.status_updated_at,
    )
