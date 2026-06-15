import asyncio
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import String, cast, func, select, text
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import ARRAY

from crewlayer.api.deps import DbDep, RedisDep, TenantDep, check_scope
from crewlayer.core.agents import portability as _portability
from crewlayer.core.agents.portability import AgentExportData
from crewlayer.core.agents.relations import (
    AgentNotFoundError,
    AgentRelations,
    CycleError,
    DuplicateSupervisorError,
    SelfRelationError,
)
from crewlayer.core.agents.status import (
    cache_status,
    read_cached_status,
)
from crewlayer.core.webhooks.dispatcher import dispatch
from crewlayer.db.models import Agent, AgentRelationTypeEnum, AgentStatusEnum, AgentStatusHistory

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


class StatusHistoryEntry(BaseModel):
    id: uuid.UUID
    status: AgentStatusEnum
    timestamp: datetime

    model_config = {"from_attributes": True}


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


class ImportResponse(BaseModel):
    agent: "AgentResponse"
    id_map: dict[str, dict[str, str]]
    warnings: list[str] = []


class RelationCreate(BaseModel):
    other_agent_id: uuid.UUID
    relation_type: AgentRelationTypeEnum


class RelationResponse(BaseModel):
    id: uuid.UUID
    supervisor_id: uuid.UUID
    subordinate_id: uuid.UUID
    relation_type: AgentRelationTypeEnum
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertsConfig(BaseModel):
    alerts_enabled: bool = True
    alert_on_consecutive_errors: int = 5
    alert_on_error_rate_percent: int = 80


class AlertsConfigUpdate(BaseModel):
    alerts_enabled: bool | None = None
    alert_on_consecutive_errors: int | None = None
    alert_on_error_rate_percent: int | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_agent_or_404(agent_id: uuid.UUID, tenant_id: uuid.UUID, db: DbDep) -> Agent:
    result = await db.execute(
        select(Agent)
        .where(Agent.id == agent_id, Agent.tenant_id == tenant_id)
        .execution_options(populate_existing=True)
    )
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
    return [TagCount(tag=str(r.tag), count=int(r._mapping["count"])) for r in rows]


# ---------------------------------------------------------------------------
# Export / Import  (registered before /{agent_id} routes)
# ---------------------------------------------------------------------------

@router.get(
    "/{agent_id}/export",
    dependencies=[check_scope("agents:read")],
    summary="Export a full agent backup as a downloadable JSON file",
)
async def export_agent(
    agent_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
) -> StreamingResponse:
    """Stream all agent data (metadata, memories, actions, episodes, sessions,
    relations) as a JSON attachment. The 90-day action window and all non-deleted
    memories are included. Embeddings are embedded in the file for portability."""
    await _get_agent_or_404(agent_id, tenant.id, db)
    filename = f"agent_{agent_id}.json"
    return StreamingResponse(
        _portability.stream_export_agent(db, tenant.id, agent_id),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post(
    "/import",
    status_code=status.HTTP_201_CREATED,
    response_model=ImportResponse,
    dependencies=[check_scope("agents:write")],
    summary="Import an agent from a previously exported JSON backup",
)
async def import_agent(
    body: AgentExportData,
    tenant: TenantDep,
    db: DbDep,
) -> ImportResponse:
    """Restore an exported agent as a brand-new agent under the authenticated tenant.

    ``export_version`` must be "1.0". The operation is fully transactional (savepoint):
    if anything fails, no partial data is left behind. Embeddings are regenerated in
    background after the response is sent so the call returns immediately.
    """
    try:
        async with db.begin_nested():
            new_agent, id_map, new_memory_ids = await _portability.import_agent(
                db, tenant.id, body
            )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Import failed: {exc}",
        )
    await db.commit()
    await db.refresh(new_agent)

    asyncio.create_task(_portability.regenerate_embeddings_background(new_memory_ids))

    warnings: list[str] = []
    if body.relations:
        warnings.append(
            f"{len(body.relations)} relation(s) from the export were not restored "
            "because referenced agents may not exist in this environment."
        )

    return ImportResponse(
        agent=AgentResponse.model_validate(new_agent),
        id_map=id_map,
        warnings=warnings,
    )


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
    rows = (await db.execute(stmt.execution_options(populate_existing=True))).scalars().all()
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
# Alert config endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/{agent_id}/alerts/config",
    response_model=AlertsConfig,
    dependencies=[check_scope("agents:read")],
    summary="Get the alert configuration for an agent",
)
async def get_alerts_config(
    agent_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
) -> AlertsConfig:
    """Return the alert thresholds stored in agent.config, with defaults filled in."""
    agent = await _get_agent_or_404(agent_id, tenant.id, db)
    cfg = agent.config
    return AlertsConfig(
        alerts_enabled=bool(cfg.get("alerts_enabled", True)),
        alert_on_consecutive_errors=int(cfg.get("alert_on_consecutive_errors", 5)),
        alert_on_error_rate_percent=int(cfg.get("alert_on_error_rate_percent", 80)),
    )


@router.patch(
    "/{agent_id}/alerts/config",
    response_model=AlertsConfig,
    dependencies=[check_scope("agents:write")],
    summary="Update the alert configuration for an agent",
)
async def update_alerts_config(
    agent_id: uuid.UUID,
    body: AlertsConfigUpdate,
    tenant: TenantDep,
    db: DbDep,
) -> AlertsConfig:
    """Partially update alert thresholds. Only provided fields are changed."""
    agent = await _get_agent_or_404(agent_id, tenant.id, db)
    config = dict(agent.config)
    if body.alerts_enabled is not None:
        config["alerts_enabled"] = body.alerts_enabled
    if body.alert_on_consecutive_errors is not None:
        config["alert_on_consecutive_errors"] = body.alert_on_consecutive_errors
    if body.alert_on_error_rate_percent is not None:
        config["alert_on_error_rate_percent"] = body.alert_on_error_rate_percent
    agent.config = config
    await db.commit()
    await db.refresh(agent)
    cfg = agent.config
    return AlertsConfig(
        alerts_enabled=bool(cfg.get("alerts_enabled", True)),
        alert_on_consecutive_errors=int(cfg.get("alert_on_consecutive_errors", 5)),
        alert_on_error_rate_percent=int(cfg.get("alert_on_error_rate_percent", 80)),
    )


# ---------------------------------------------------------------------------
# Status endpoints
# ---------------------------------------------------------------------------

@router.patch(
    "/{agent_id}/status",
    response_model=AgentResponse,
    dependencies=[check_scope("agents:write")],
)
async def update_agent_status(
    agent_id: uuid.UUID,
    body: AgentStatusUpdate,
    tenant: TenantDep,
    db: DbDep,
    redis: RedisDep,
) -> AgentResponse:
    """Update the runtime status of an agent (idle / working / error)."""
    now = datetime.now(UTC)

    upd = await db.execute(
        sa_update(Agent)
        .where(Agent.id == agent_id, Agent.tenant_id == tenant.id)
        .values(
            status=body.status,
            status_updated_at=now,
            current_session_id=body.session_id,
        )
        .execution_options(synchronize_session=False)
    )
    if upd.rowcount == 0:  # type: ignore[attr-defined]
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agente no encontrado")

    db.add(AgentStatusHistory(
        agent_id=agent_id,
        tenant_id=tenant.id,
        status=body.status,
        timestamp=now,
    ))
    await db.commit()

    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant.id)
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agente no encontrado")

    await cache_status(agent.id, agent.status, agent.current_session_id, agent.status_updated_at, redis)
    asyncio.create_task(
        dispatch(tenant.id, "agent.status_changed", {
            "agent_id": str(agent_id),
            "status": agent.status.value,
        })
    )
    return AgentResponse.model_validate(agent)


@router.get(
    "/{agent_id}/status/history",
    response_model=list[StatusHistoryEntry],
    dependencies=[check_scope("agents:read")],
)
async def get_agent_status_history(
    agent_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
    limit: int = Query(20, ge=1, le=100),
) -> list[StatusHistoryEntry]:
    """Return the N most recent status transitions for an agent, newest first."""
    await _get_agent_or_404(agent_id, tenant.id, db)
    result = await db.execute(
        select(AgentStatusHistory)
        .where(AgentStatusHistory.agent_id == agent_id, AgentStatusHistory.tenant_id == tenant.id)
        .order_by(AgentStatusHistory.timestamp.desc())
        .limit(limit)
    )
    return [StatusHistoryEntry.model_validate(r) for r in result.scalars().all()]


# ---------------------------------------------------------------------------
# Relation endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/{agent_id}/relations",
    status_code=status.HTTP_201_CREATED,
    response_model=RelationResponse,
    dependencies=[check_scope("agents:write")],
    summary="Define a relation between this agent and another",
)
async def set_relation(
    agent_id: uuid.UUID,
    body: RelationCreate,
    tenant: TenantDep,
    db: DbDep,
) -> RelationResponse:
    """Create or update a relation.

    ``agent_id`` is always the supervisor/from side. For ``supervisor`` type,
    ``agent_id`` supervises ``other_agent_id``. An agent can only have one supervisor
    but multiple collaborators or delegates.
    """
    ar = AgentRelations(db)
    try:
        rel = await ar.set_relation(
            tenant.id, agent_id, body.other_agent_id, body.relation_type
        )
    except SelfRelationError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Un agente no puede relacionarse consigo mismo",
        )
    except CycleError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="La relación crearía un ciclo en la jerarquía",
        )
    except DuplicateSupervisorError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="El agente ya tiene un supervisor asignado",
        )
    except AgentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agente no encontrado",
        )
    await db.commit()
    await db.refresh(rel)
    return RelationResponse.model_validate(rel)


@router.get(
    "/{agent_id}/relations",
    response_model=list[RelationResponse],
    dependencies=[check_scope("agents:read")],
    summary="List all relations of this agent",
)
async def list_relations(
    agent_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
) -> list[RelationResponse]:
    """Return every relation where this agent appears as supervisor or subordinate."""
    await _get_agent_or_404(agent_id, tenant.id, db)
    ar = AgentRelations(db)
    rels = await ar.get_all_relations(tenant.id, agent_id)
    return [RelationResponse.model_validate(r) for r in rels]


@router.get(
    "/{agent_id}/tree",
    dependencies=[check_scope("agents:read")],
    summary="Return the full downward hierarchy tree",
)
async def get_tree(
    agent_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
) -> dict[str, Any]:
    """Return the hierarchical tree of supervisor→subordinate relations rooted at agent_id."""
    ar = AgentRelations(db)
    try:
        return await ar.get_tree(tenant.id, agent_id)
    except AgentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agente no encontrado",
        )


@router.delete(
    "/{agent_id}/relations/{other_agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[check_scope("agents:write")],
    summary="Delete the relation between two agents",
)
async def delete_relation(
    agent_id: uuid.UUID,
    other_agent_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
) -> None:
    """Remove the relation between agent_id and other_agent_id in either direction."""
    ar = AgentRelations(db)
    deleted = await ar.delete_relation(tenant.id, agent_id, other_agent_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Relación no encontrada",
        )
    await db.commit()


# ---------------------------------------------------------------------------
# Status endpoints
# ---------------------------------------------------------------------------

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
