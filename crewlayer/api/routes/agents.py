import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from crewlayer.api.deps import DbDep, TenantDep, check_scope
from crewlayer.db.models import Agent

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

    model_config = {"from_attributes": True}


@router.post("", status_code=status.HTTP_201_CREATED, response_model=AgentResponse)
async def create_agent(body: AgentCreate, tenant: TenantDep, db: DbDep) -> AgentResponse:
    """Create a new agent for the authenticated tenant."""
    agent = Agent(tenant_id=tenant.id, name=body.name, description=body.description, config=body.config)
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return AgentResponse.model_validate(agent)


@router.get("", response_model=list[AgentResponse], dependencies=[check_scope("agents:read")])
async def list_agents(tenant: TenantDep, db: DbDep) -> list[AgentResponse]:
    rows = (await db.execute(select(Agent).where(Agent.tenant_id == tenant.id))).scalars().all()
    return [AgentResponse.model_validate(a) for a in rows]


@router.get("/{agent_id}", response_model=AgentResponse, dependencies=[check_scope("agents:read")])
async def get_agent(agent_id: uuid.UUID, tenant: TenantDep, db: DbDep) -> AgentResponse:
    result = await db.execute(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant.id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agente no encontrado")
    return AgentResponse.model_validate(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: uuid.UUID, tenant: TenantDep, db: DbDep) -> None:
    result = await db.execute(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant.id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agente no encontrado")
    await db.delete(agent)
    await db.commit()
