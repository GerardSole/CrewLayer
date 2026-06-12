import asyncio
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from sse_starlette.sse import EventSourceResponse  # type: ignore[attr-defined]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.api.deps import DbDep, RedisDep, TenantDep, check_scope
from crewlayer.api.schemas.actions import (
    ActionCreate,
    ActionListResponse,
    ActionResponse,
    ActionStatsResponse,
    ReplayCreate,
    ReplayListResponse,
    ReplayResponse,
    ToolStatResponse,
)
from crewlayer.core.actions.alerts import check_and_fire_alerts
from crewlayer.core.actions.logger import ActionFilters, ActionLogger
from crewlayer.core.evaluation.anomalies import AnomalyManager
from crewlayer.core.webhooks.dispatcher import dispatch
from crewlayer.db.models import Action as _BGAction
from crewlayer.core.actions.replay import (
    create_replay,
    get_replay,
    list_replays,
    replay_event_stream,
)
from crewlayer.db.models import (
    ActionStatus,
    Agent,
    AnomalySeverityEnum,
    Replay,
    ReplayStatusEnum,
    Session,
    SessionStatus,
)
router = APIRouter()


async def _detect_anomalies_bg(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    action_id: uuid.UUID,
    agent_config: dict,
) -> None:
    """Run anomaly detection in a dedicated session so it never blocks the request.

    Uses NullPool so this task never reuses connections across event-loop boundaries.
    """
    import logging as _logging
    import contextlib
    import redis.asyncio as aioredis
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy.pool import NullPool
    from crewlayer.core.config import settings as _settings
    _log = _logging.getLogger(__name__)

    bg_engine = create_async_engine(_settings.DATABASE_URL, poolclass=NullPool)
    BGSession = async_sessionmaker(bg_engine, expire_on_commit=False)
    try:
        redis_client = aioredis.from_url(_settings.REDIS_URL, decode_responses=True)
        try:
            async with BGSession() as db:
                action_result = await db.execute(
                    select(_BGAction).where(_BGAction.id == action_id)
                )
                action = action_result.scalar_one_or_none()
                if action is None:
                    return
                mgr = AnomalyManager(db)
                anomalies = await mgr.detect(
                    tenant_id, agent_id, action, agent_config, redis_client
                )
                await db.commit()
                for anomaly in anomalies:
                    if anomaly.severity == AnomalySeverityEnum.high:
                        await dispatch(
                            tenant_id,
                            "evaluation.anomaly_detected",
                            {
                                "anomaly_id": str(anomaly.id),
                                "agent_id": str(agent_id),
                                "anomaly_type": anomaly.anomaly_type.value,
                                "severity": anomaly.severity.value,
                                "details": anomaly.details,
                            },
                        )
        finally:
            await redis_client.aclose()
    except Exception:
        _log.exception("Anomaly detection background task failed")
    finally:
        with contextlib.suppress(Exception):
            await bg_engine.dispose()


async def _validate_session(
    session_id: uuid.UUID | None,
    agent_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    """If session_id is provided, verify it is active and belongs to this agent/tenant."""
    if session_id is None:
        return
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.tenant_id == tenant_id)
    )
    sess = result.scalar_one_or_none()
    if sess is None or sess.agent_id != agent_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sesión no encontrada")
    if sess.status != SessionStatus.active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="La sesión no está activa")


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
    dependencies=[check_scope("actions:write")],
)
async def log_action(
    agent_id: uuid.UUID,
    body: ActionCreate,
    tenant: TenantDep,
    db: DbDep,
    redis: RedisDep,
) -> ActionResponse:
    """Register an immutable action record for an agent."""
    agent = await _get_agent(agent_id, tenant.id, db)
    await _validate_session(body.session_id, agent_id, tenant.id, db)
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
    asyncio.create_task(
        _detect_anomalies_bg(tenant.id, agent_id, action.id, agent.config or {})
    )
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
    await check_and_fire_alerts(
        tenant_id=tenant.id,
        agent_id=agent_id,
        agent_name=agent.name,
        agent_config=agent.config,
        action_status=action.status,
        action_id=action.id,
        db=db,
        redis=redis,
    )
    return ActionResponse.model_validate(action)


@router.get(
    "/agents/{agent_id}/actions/stats",
    response_model=ActionStatsResponse,
    dependencies=[check_scope("actions:read")],
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
    dependencies=[check_scope("actions:read")],
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
    dependencies=[check_scope("actions:read")],
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


# ─── Replay endpoints ─────────────────────────────────────────────────────────


async def _get_replay_or_404(
    agent_id: uuid.UUID,
    tenant_id: uuid.UUID,
    replay_id: uuid.UUID,
    db: AsyncSession,
) -> Replay:
    replay = await get_replay(db, tenant_id, agent_id, replay_id)
    if replay is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Replay no encontrado")
    return replay


@router.post(
    "/agents/{agent_id}/replays",
    status_code=status.HTTP_201_CREATED,
    response_model=ReplayResponse,
    dependencies=[check_scope("actions:read")],
)
async def create_replay_job(
    agent_id: uuid.UUID,
    body: ReplayCreate,
    tenant: TenantDep,
    db: DbDep,
) -> ReplayResponse:
    """Create a pending replay job for a time window of an agent's actions."""
    await _get_agent(agent_id, tenant.id, db)
    replay = await create_replay(
        db,
        tenant_id=tenant.id,
        agent_id=agent_id,
        from_timestamp=body.from_timestamp,
        to_timestamp=body.to_timestamp,
        speed=body.speed,
    )
    await db.commit()
    await db.refresh(replay)
    return ReplayResponse.model_validate(replay)


@router.get(
    "/agents/{agent_id}/replays",
    response_model=ReplayListResponse,
    dependencies=[check_scope("actions:read")],
)
async def list_agent_replays(
    agent_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
) -> ReplayListResponse:
    """List all replay jobs for an agent, newest first."""
    await _get_agent(agent_id, tenant.id, db)
    replays = await list_replays(db, tenant.id, agent_id)
    return ReplayListResponse(
        items=[ReplayResponse.model_validate(r) for r in replays],
        count=len(replays),
    )


@router.get(
    "/agents/{agent_id}/replays/{replay_id}",
    response_model=ReplayResponse,
    dependencies=[check_scope("actions:read")],
)
async def get_replay_detail(
    agent_id: uuid.UUID,
    replay_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
) -> ReplayResponse:
    """Get a single replay job by ID."""
    await _get_agent(agent_id, tenant.id, db)
    replay = await _get_replay_or_404(agent_id, tenant.id, replay_id, db)
    return ReplayResponse.model_validate(replay)


@router.get(
    "/agents/{agent_id}/replays/{replay_id}/stream",
    dependencies=[check_scope("actions:read")],
)
async def stream_replay(
    agent_id: uuid.UUID,
    replay_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
    request: Request,
) -> EventSourceResponse:
    """Stream a replay job as SSE events in chronological order.

    Emits one ``action`` event per recorded action (respecting the configured
    speed multiplier), then a final ``completed`` event when done.
    Replay transitions: pending/completed/failed → running → completed.
    Returns 409 if the replay is already running.
    """
    await _get_agent(agent_id, tenant.id, db)
    replay = await _get_replay_or_404(agent_id, tenant.id, replay_id, db)
    if replay.status == ReplayStatusEnum.running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El replay ya está en ejecución",
        )
    return EventSourceResponse(replay_event_stream(db, replay, request.is_disconnected))
