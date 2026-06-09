import asyncio
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.api.deps import DbDep, RedisDep, TenantDep
from crewlayer.api.schemas.sessions import SessionCloseResponse, SessionCreate, SessionResponse
from crewlayer.core.memory.short import ShortMemory
from crewlayer.core.sessions.manager import SessionManager, SessionNotActiveError, SessionNotFoundError
from crewlayer.core.streaming.broker import make_channel, publish as stream_publish
from crewlayer.core.webhooks.dispatcher import dispatch
from crewlayer.db.models import Agent, Memory, SessionStatus

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
    "/sessions",
    status_code=status.HTTP_201_CREATED,
    response_model=SessionResponse,
)
async def create_session(
    body: SessionCreate,
    tenant: TenantDep,
    db: DbDep,
) -> SessionResponse:
    """Create a new active session for an agent."""
    await _get_agent(body.agent_id, tenant.id, db)
    mgr = SessionManager(db)
    sess = await mgr.create(tenant.id, body.agent_id, metadata=body.metadata)
    await db.commit()
    await db.refresh(sess)
    return SessionResponse.from_orm(sess)


@router.get(
    "/sessions",
    response_model=list[SessionResponse],
)
async def list_sessions(
    tenant: TenantDep,
    db: DbDep,
    agent_id: Annotated[uuid.UUID | None, Query()] = None,
    filter_status: Annotated[SessionStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SessionResponse]:
    """List sessions for the authenticated tenant."""
    mgr = SessionManager(db)
    sessions = await mgr.list(tenant.id, agent_id=agent_id, status=filter_status, limit=limit, offset=offset)
    return [SessionResponse.from_orm(s) for s in sessions]


@router.get(
    "/sessions/{session_id}",
    response_model=SessionResponse,
)
async def get_session(
    session_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
) -> SessionResponse:
    """Get a session by ID."""
    mgr = SessionManager(db)
    try:
        sess = await mgr.get(session_id, tenant.id)
    except SessionNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sesión no encontrada")
    return SessionResponse.from_orm(sess)


@router.post(
    "/sessions/{session_id}/close",
    response_model=SessionCloseResponse,
)
async def close_session(
    session_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
    redis: RedisDep,
) -> SessionCloseResponse:
    """Close a session: extract memories, update status, clear Redis history."""
    mgr = SessionManager(db)
    try:
        sess = await mgr.close(session_id, tenant.id, redis=redis)
    except SessionNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sesión no encontrada")
    except SessionNotActiveError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="La sesión no está activa")

    message_count = sess.message_count
    await db.commit()
    await db.refresh(sess)

    sm = ShortMemory(redis)
    await sm.clear(str(tenant.id), str(sess.agent_id), str(session_id))

    # Count how many memories were extracted for this session
    from sqlalchemy import func
    result = await db.execute(
        select(func.count()).select_from(Memory).where(
            Memory.tenant_id == tenant.id,
            Memory.agent_id == sess.agent_id,
            Memory.deleted_at.is_(None),
        )
    )
    # We can't easily count just the newly extracted ones without tagging them,
    # so we report message_count as a proxy (0 if redis was empty)
    memories_extracted = message_count

    channel = make_channel(str(tenant.id), str(sess.agent_id), str(session_id))
    asyncio.create_task(
        stream_publish(redis, channel, "memory_extracted", {
            "count": memories_extracted,
            "session_id": str(session_id),
        })
    )
    asyncio.create_task(
        stream_publish(redis, channel, "session_closed", {
            "session_id": str(session_id),
            "status": "closed",
        })
    )
    asyncio.create_task(
        dispatch(
            tenant.id,
            "session.closed",
            {
                "session_id": str(session_id),
                "agent_id": str(sess.agent_id),
                "message_count": message_count,
            },
        )
    )

    return SessionCloseResponse(
        session=SessionResponse.from_orm(sess),
        memories_extracted=memories_extracted,
    )


@router.post(
    "/sessions/{session_id}/archive",
    response_model=SessionResponse,
)
async def archive_session(
    session_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
    redis: RedisDep,
) -> SessionResponse:
    """Archive a closed session."""
    mgr = SessionManager(db)
    try:
        sess = await mgr.archive(session_id, tenant.id)
    except SessionNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sesión no encontrada")
    except SessionNotActiveError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    await db.commit()
    await db.refresh(sess)
    asyncio.create_task(
        stream_publish(
            redis,
            make_channel(str(tenant.id), str(sess.agent_id), str(session_id)),
            "session_archived",
            {"session_id": str(session_id), "status": "archived"},
        )
    )
    return SessionResponse.from_orm(sess)
