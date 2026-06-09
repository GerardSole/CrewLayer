import asyncio
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.api.deps import DbDep, TenantDep
from crewlayer.api.schemas.actions import (
    ActionCreate,
    ActionListResponse,
    ActionResponse,
    ActionStatsResponse,
    ToolStatResponse,
)
from crewlayer.core.actions.logger import ActionFilters, ActionLogger
from crewlayer.core.webhooks.dispatcher import dispatch
from crewlayer.db.models import ActionStatus, Agent

router = APIRouter()


async def _get_agent(agent_id: uuid.UUID, tenant_id: uuid.UUID, db: AsyncSession) -> Agent:
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id)
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agente no encontrado")
    return agent


@router.post(
    "/agents/{agent_id}/actions",
    status_code=status.HTTP_201_CREATED,
    response_model=ActionResponse,
)
async def log_action(
    agent_id: uuid.UUID,
    body: ActionCreate,
    tenant: TenantDep,
    db: DbDep,
) -> ActionResponse:
    """Register an immutable action record for an agent."""
    await _get_agent(agent_id, tenant.id, db)
    logger = ActionLogger(db)
    action = await logger.log(
        tenant_id=tenant.id,
        agent_id=agent_id,
        tool_name=body.tool_name,
        input_params=body.input_params,
        output_result=body.output_result,
        status=body.status,
        session_id=body.session_id,
        duration_ms=body.duration_ms,
        error_msg=body.error_msg,
        metadata=body.metadata,
    )
    await db.commit()
    await db.refresh(action)
    _webhook_payload = {
        "action_id": str(action.id),
        "agent_id": str(agent_id),
        "tool_name": action.tool_name,
        "status": action.status.value,
        "duration_ms": action.duration_ms,
    }
    asyncio.create_task(dispatch(tenant.id, "action.logged", _webhook_payload))
    if action.status in (ActionStatus.error, ActionStatus.timeout):
        asyncio.create_task(dispatch(tenant.id, "action.failed", _webhook_payload))
    return ActionResponse.model_validate(action)


@router.get(
    "/agents/{agent_id}/actions/stats",
    response_model=ActionStatsResponse,
)
async def get_stats(
    agent_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
) -> ActionStatsResponse:
    """Aggregate statistics: totals, average duration, error rate, breakdown by tool."""
    await _get_agent(agent_id, tenant.id, db)
    logger = ActionLogger(db)
    stats = await logger.stats(tenant.id, agent_id)
    return ActionStatsResponse(
        total_actions=stats.total_actions,
        error_rate=stats.error_rate,
        avg_duration_ms=stats.avg_duration_ms,
        by_tool=[
            ToolStatResponse(
                tool_name=t.tool_name,
                count=t.count,
                avg_duration_ms=t.avg_duration_ms,
                error_rate=t.error_rate,
            )
            for t in stats.by_tool
        ],
    )


@router.get(
    "/agents/{agent_id}/actions/{action_id}",
    response_model=ActionResponse,
)
async def get_action(
    agent_id: uuid.UUID,
    action_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
) -> ActionResponse:
    """Retrieve a single action record."""
    await _get_agent(agent_id, tenant.id, db)
    logger = ActionLogger(db)
    action = await logger.get(tenant.id, action_id)
    if action is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Acción no encontrada")
    if action.agent_id != agent_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Acción no encontrada")
    return ActionResponse.model_validate(action)


@router.get(
    "/agents/{agent_id}/actions",
    response_model=ActionListResponse,
)
async def list_actions(
    agent_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
    tool: Annotated[str | None, Query()] = None,
    filter_status: Annotated[ActionStatus | None, Query(alias="status")] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> ActionListResponse:
    """List actions for an agent with optional filters and cursor-based pagination."""
    await _get_agent(agent_id, tenant.id, db)
    logger = ActionLogger(db)
    filters = ActionFilters(
        tool_name=tool,
        status=filter_status,
        since=since,
        until=until,
        limit=limit,
        cursor=cursor,
    )
    actions, next_cursor = await logger.list(tenant.id, agent_id, filters)
    return ActionListResponse(
        items=[ActionResponse.model_validate(a) for a in actions],
        count=len(actions),
        next_cursor=next_cursor,
    )
