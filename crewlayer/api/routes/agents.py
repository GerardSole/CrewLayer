import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select

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


class AgentResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: str | None = None
    config: dict[str, Any]
    status: AgentStatusEnum
    current_session_id: uuid.UUID | None = None
    status_updated_at: datetime

    model_config = {"from_attributes": True}


class AgentStatusUpdate(BaseModel):
    status: AgentStatusEnum
    session_id: uuid.UUID | None = None


class AgentStatusResponse(BaseModel):
    agent_id: uuid.UUID
    status: AgentStatusEnum
    current_session_id: uuid.UUID | None = None
    updated_at: datetime


@router.post("", status_code=status.HTTP_201_CREATED, response_model=AgentResponse)
async def create_agent(body: AgentCreate, tenant: TenantDep, db: DbDep) -> AgentResponse:
    """Create a new agent for the authenticated tenant."""
    agent = Agent(tenant_id=tenant.id, name=body.name, description=body.description, config=body.config)
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return AgentResponse.model_validate(agent)


@router.get("", response_model=list[AgentResponse], dependencies=[check_scope("agents:read")])
async def list_agents(
    tenant: TenantDep,
    db: DbDep,
    filter_status: Annotated[AgentStatusEnum | None, Query(alias="status")] = None,
) -> list[AgentResponse]:
    """List agents for the authenticated tenant with optional status filter."""
    stmt = select(Agent).where(Agent.tenant_id == tenant.id)
    if filter_status is not None:
        stmt = stmt.where(Agent.status == filter_status)
    rows = (await db.execute(stmt)).scalars().all()
    return [AgentResponse.model_validate(a) for a in rows]


@router.get("/{agent_id}", response_model=AgentResponse, dependencies=[check_scope("agents:read")])
async def get_agent(agent_id: uuid.UUID, tenant: TenantDep, db: DbDep) -> AgentResponse:
    """Get a single agent by ID."""
    result = await db.execute(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant.id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agente no encontrado")
    return AgentResponse.model_validate(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: uuid.UUID, tenant: TenantDep, db: DbDep) -> None:
    """Delete an agent and all its associated data (cascade)."""
    result = await db.execute(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant.id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agente no encontrado")
    await db.delete(agent)
    await db.commit()


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
    result = await db.execute(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant.id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agente no encontrado")

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

    # Cache miss — read from DB and warm the cache
    result = await db.execute(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant.id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agente no encontrado")

    await cache_status(agent.id, agent.status, agent.current_session_id, agent.status_updated_at, redis)

    return AgentStatusResponse(
        agent_id=agent.id,
        status=agent.status,
        current_session_id=agent.current_session_id,
        updated_at=agent.status_updated_at,
    )
