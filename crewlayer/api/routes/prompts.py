"""Prompt version control endpoints.

All routes are scoped under /v1/agents/{agent_id}/prompts and require
agents:write (mutations) or agents:read (reads).
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.api.deps import ApiKeyDep, DbDep, TenantDep, check_scope
from crewlayer.api.schemas.prompts import (
    DiffLineResponse,
    PromptDiffResponse,
    PromptVersionCreate,
    PromptVersionListResponse,
    PromptVersionResponse,
)
from crewlayer.core.prompts.manager import (
    NoActiveVersionError,
    NoPreviousVersionError,
    PromptManager,
    PromptNotFoundError,
)
from crewlayer.db.models import Agent

router = APIRouter()


async def _get_agent(
    agent_id: uuid.UUID, tenant_id: uuid.UUID, db: AsyncSession
) -> Agent:
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id)
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agente no encontrado")
    return agent


@router.post(
    "/agents/{agent_id}/prompts",
    status_code=status.HTTP_201_CREATED,
    response_model=PromptVersionResponse,
    dependencies=[check_scope("agents:write")],
)
async def create_prompt_version(
    agent_id: uuid.UUID,
    body: PromptVersionCreate,
    tenant: TenantDep,
    db: DbDep,
    api_key: ApiKeyDep,
) -> PromptVersionResponse:
    """Create a new prompt version for an agent. Version number is auto-incremented."""
    await _get_agent(agent_id, tenant.id, db)
    manager = PromptManager(db)
    pv = await manager.create_version(
        tenant_id=tenant.id,
        agent_id=agent_id,
        content=body.content,
        description=body.description,
        created_by=api_key.id,
    )
    await db.commit()
    await db.refresh(pv)
    return PromptVersionResponse.model_validate(pv)


@router.get(
    "/agents/{agent_id}/prompts",
    response_model=PromptVersionListResponse,
    dependencies=[check_scope("agents:read")],
)
async def list_prompt_versions(
    agent_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
) -> PromptVersionListResponse:
    """List all prompt versions for an agent, ordered by version descending."""
    await _get_agent(agent_id, tenant.id, db)
    manager = PromptManager(db)
    versions = await manager.list_versions(tenant.id, agent_id)
    return PromptVersionListResponse(
        items=[PromptVersionResponse.model_validate(v) for v in versions],
        count=len(versions),
    )


@router.get(
    "/agents/{agent_id}/prompts/active",
    response_model=PromptVersionResponse,
    dependencies=[check_scope("agents:read")],
)
async def get_active_prompt(
    agent_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
) -> PromptVersionResponse:
    """Return the currently active prompt version."""
    await _get_agent(agent_id, tenant.id, db)
    manager = PromptManager(db)
    pv = await manager.get_active(tenant.id, agent_id)
    if pv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hay ninguna versión activa para este agente",
        )
    return PromptVersionResponse.model_validate(pv)


@router.post(
    "/agents/{agent_id}/prompts/rollback",
    response_model=PromptVersionResponse,
    dependencies=[check_scope("agents:write")],
)
async def rollback_prompt(
    agent_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
) -> PromptVersionResponse:
    """Activate the version immediately before the currently active one."""
    await _get_agent(agent_id, tenant.id, db)
    manager = PromptManager(db)
    try:
        pv = await manager.rollback(tenant.id, agent_id)
    except NoActiveVersionError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No hay versión activa desde la que hacer rollback",
        )
    except NoPreviousVersionError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No existe una versión anterior a la activa",
        )
    await db.commit()
    await db.refresh(pv)
    return PromptVersionResponse.model_validate(pv)


@router.get(
    "/agents/{agent_id}/prompts/diff",
    response_model=PromptDiffResponse,
    dependencies=[check_scope("agents:read")],
)
async def diff_prompt_versions(
    agent_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
    a: Annotated[uuid.UUID, Query(description="ID de la versión base")],
    b: Annotated[uuid.UUID, Query(description="ID de la versión comparada")],
) -> PromptDiffResponse:
    """Return a line-by-line diff between two prompt versions."""
    await _get_agent(agent_id, tenant.id, db)
    manager = PromptManager(db)
    try:
        lines = await manager.diff(tenant.id, a, b)
    except PromptNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return PromptDiffResponse(
        version_id_a=a,
        version_id_b=b,
        lines=[DiffLineResponse(**vars(line)) for line in lines],
    )


@router.get(
    "/agents/{agent_id}/prompts/{version_id}",
    response_model=PromptVersionResponse,
    dependencies=[check_scope("agents:read")],
)
async def get_prompt_version(
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
) -> PromptVersionResponse:
    """Return a specific prompt version by ID."""
    await _get_agent(agent_id, tenant.id, db)
    manager = PromptManager(db)
    try:
        pv = await manager.get_version_detail(tenant.id, version_id)
    except PromptNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Versión no encontrada")
    if pv.agent_id != agent_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Versión no encontrada")
    return PromptVersionResponse.model_validate(pv)


@router.post(
    "/agents/{agent_id}/prompts/{version_id}/activate",
    response_model=PromptVersionResponse,
    dependencies=[check_scope("agents:write")],
)
async def activate_prompt_version(
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
) -> PromptVersionResponse:
    """Activate a specific prompt version. Deactivates any previously active version."""
    await _get_agent(agent_id, tenant.id, db)
    manager = PromptManager(db)
    try:
        pv = await manager.activate(tenant.id, agent_id, version_id)
    except PromptNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Versión no encontrada")
    await db.commit()
    await db.refresh(pv)
    return PromptVersionResponse.model_validate(pv)
