import asyncio
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.api.deps import DbDep, RedisDep, TenantDep
from crewlayer.core.webhooks.dispatcher import dispatch
from crewlayer.api.schemas.memory import (
    ExtractRequest,
    ExtractResponse,
    MemoryListResponse,
    MemoryResponse,
    MessageIn,
    MessageOut,
    RecallRequest,
    RecallResponse,
    ShortMemoryResponse,
)
from crewlayer.core.memory.extractor import extract_and_save
from crewlayer.core.memory.long import LongMemory
from crewlayer.core.memory.short import ShortMemory
from crewlayer.core.streaming.broker import make_channel, publish as stream_publish
from crewlayer.db.models import Agent, Memory, Session, SessionStatus

router = APIRouter()


async def _validate_session(
    session_id_raw: str,
    agent_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    """Validate session_id if it is a UUID; non-UUID strings skip validation (backward compat)."""
    try:
        sid = uuid.UUID(session_id_raw)
    except ValueError:
        return
    result = await db.execute(
        select(Session).where(Session.id == sid, Session.tenant_id == tenant_id)
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
    "/agents/{agent_id}/memory/messages",
    status_code=status.HTTP_201_CREATED,
    response_model=ShortMemoryResponse,
)
async def append_message(
    agent_id: uuid.UUID,
    body: MessageIn,
    tenant: TenantDep,
    db: DbDep,
    redis: RedisDep,
    session_id: Annotated[str, Query()] = "default",
) -> ShortMemoryResponse:
    """Append a message to the agent's short-term (Redis) memory for a session."""
    await _get_agent(agent_id, tenant.id, db)
    await _validate_session(session_id, agent_id, tenant.id, db)
    sm = ShortMemory(redis)
    msg_data = body.model_dump()
    await sm.append_message(str(tenant.id), str(agent_id), session_id, msg_data)
    # Publish to SSE stream so live subscribers receive the message immediately
    asyncio.create_task(
        stream_publish(
            redis,
            make_channel(str(tenant.id), str(agent_id), session_id),
            "message",
            msg_data,
        )
    )
    messages_raw = await sm.get_messages(str(tenant.id), str(agent_id), session_id)
    return ShortMemoryResponse(
        session_id=session_id,
        messages=[MessageOut(**m) for m in messages_raw],
        count=len(messages_raw),
    )


@router.get(
    "/agents/{agent_id}/memory/messages",
    response_model=ShortMemoryResponse,
)
async def get_messages(
    agent_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
    redis: RedisDep,
    session_id: Annotated[str, Query()] = "default",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ShortMemoryResponse:
    """Retrieve recent messages from the agent's short-term memory for a session."""
    await _get_agent(agent_id, tenant.id, db)
    sm = ShortMemory(redis)
    messages_raw = await sm.get_messages(str(tenant.id), str(agent_id), session_id, limit=limit)
    return ShortMemoryResponse(
        session_id=session_id,
        messages=[MessageOut(**m) for m in messages_raw],
        count=len(messages_raw),
    )


@router.post(
    "/agents/{agent_id}/memory/recall",
    response_model=RecallResponse,
)
async def recall(
    agent_id: uuid.UUID,
    body: RecallRequest,
    tenant: TenantDep,
    db: DbDep,
    redis: RedisDep,
) -> RecallResponse:
    """Semantic recall: find long-term memories similar to the query text."""
    await _get_agent(agent_id, tenant.id, db)
    lm = LongMemory(db, redis)
    results = await lm.recall(
        tenant.id,
        agent_id,
        body.query,
        limit=body.limit,
        min_similarity=body.min_similarity,
    )
    return RecallResponse(
        query=body.query,
        results=[
            MemoryResponse(
                id=mem.id,
                agent_id=mem.agent_id,
                content=mem.content,
                summary=mem.summary,
                importance=mem.importance,
                base_importance=mem.base_importance,
                tags=mem.tags,
                created_at=mem.created_at,
                similarity=sim,
            )
            for mem, sim in results
        ],
    )


@router.post(
    "/agents/{agent_id}/memory/extract",
    response_model=ExtractResponse,
)
async def extract(
    agent_id: uuid.UUID,
    body: ExtractRequest,
    tenant: TenantDep,
    db: DbDep,
    redis: RedisDep,
) -> ExtractResponse:
    """Extract facts from a conversation with Claude and persist as long-term memories."""
    await _get_agent(agent_id, tenant.id, db)
    lm = LongMemory(db, redis)
    memory_ids = await extract_and_save(tenant.id, agent_id, body.conversation, lm)
    await db.commit()
    asyncio.create_task(
        dispatch(
            tenant.id,
            "memory.extracted",
            {"agent_id": str(agent_id), "memory_ids": [str(i) for i in memory_ids]},
        )
    )
    return ExtractResponse(extracted_count=len(memory_ids), memory_ids=memory_ids)


@router.get(
    "/agents/{agent_id}/memory",
    response_model=MemoryListResponse,
)
async def list_memories(
    agent_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> MemoryListResponse:
    """List all non-deleted long-term memories for an agent, paginated."""
    await _get_agent(agent_id, tenant.id, db)

    base = select(Memory).where(
        Memory.agent_id == agent_id,
        Memory.tenant_id == tenant.id,
        Memory.deleted_at.is_(None),
    )
    total_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total: int = total_result.scalar_one()

    rows = (
        await db.execute(
            base.order_by(Memory.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    return MemoryListResponse(
        items=[
            MemoryResponse(
                id=m.id,
                agent_id=m.agent_id,
                content=m.content,
                summary=m.summary,
                importance=m.importance,
                base_importance=m.base_importance,
                tags=m.tags,
                created_at=m.created_at,
            )
            for m in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.delete(
    "/agents/{agent_id}/memory/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_memory(
    agent_id: uuid.UUID,
    memory_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
) -> None:
    """Soft-delete a long-term memory."""
    await _get_agent(agent_id, tenant.id, db)
    lm = LongMemory(db)
    deleted = await lm.forget(memory_id, tenant.id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Memoria no encontrada"
        )
    await db.commit()
