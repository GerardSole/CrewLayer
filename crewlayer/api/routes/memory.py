import asyncio
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.api.deps import DbDep, RedisDep, TenantDep, check_scope
from crewlayer.api.schemas.memory import (
    ArchiveRequest,
    ArchiveResponse,
    ExtractRequest,
    ExtractResponse,
    MemoryCreateRequest,
    MemoryHistoryEntry,
    MemoryHistoryResponse,
    MemoryListResponse,
    MemoryMiniResponse,
    MemoryResponse,
    MemoryStatsResponse,
    MessageIn,
    MessageOut,
    RecallRequest,
    RecallResponse,
    ShortMemoryResponse,
)
from crewlayer.core.memory.extractor import extract_and_save
from crewlayer.core.memory.long import LongMemory
from crewlayer.core.memory.short import ShortMemory
from crewlayer.core.streaming.broker import make_channel
from crewlayer.core.streaming.broker import publish as stream_publish
from crewlayer.core.webhooks.dispatcher import dispatch
from crewlayer.db.models import Agent, Memory, MemoryStatusEnum, Session, SessionStatus

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
    dependencies=[check_scope("memory:write")],
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
    dependencies=[check_scope("memory:read")],
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
    dependencies=[check_scope("memory:read")],
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
                merged_from=mem.merged_from,
                created_at=mem.created_at,
                similarity=sim,
            )
            for mem, sim in results
        ],
    )


@router.post(
    "/agents/{agent_id}/memory/extract",
    response_model=ExtractResponse,
    dependencies=[check_scope("memory:write")],
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
    memory_ids = await extract_and_save(tenant.id, agent_id, body.conversation, lm, session_id=body.session_id)
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
    "/agents/{agent_id}/memories/stats",
    response_model=MemoryStatsResponse,
    dependencies=[check_scope("memory:read")],
)
async def memory_stats(
    agent_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
) -> MemoryStatsResponse:
    """Return aggregate statistics for an agent's memories."""
    await _get_agent(agent_id, tenant.id, db)

    base_filter = [
        Memory.agent_id == agent_id,
        Memory.tenant_id == tenant.id,
        Memory.deleted_at.is_(None),
    ]

    # Count by status in a single query
    count_rows = (
        await db.execute(
            select(Memory.status, func.count(Memory.id))
            .where(*base_filter)
            .group_by(Memory.status)
        )
    ).all()
    count_map: dict[str, Any] = {row[0]: row[1] for row in count_rows}
    total_active = count_map.get(MemoryStatusEnum.active, 0)
    total_archived = count_map.get(MemoryStatusEnum.archived, 0)

    # Average importance across active memories
    avg_val = (
        await db.execute(
            select(func.avg(Memory.importance)).where(
                *base_filter, Memory.status == MemoryStatusEnum.active
            )
        )
    ).scalar_one_or_none()
    avg_importance = round(float(avg_val or 0.0), 6)

    # Oldest active memory
    oldest = (
        await db.execute(
            select(Memory)
            .where(*base_filter, Memory.status == MemoryStatusEnum.active)
            .order_by(Memory.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()

    # Most accessed active memory
    most_accessed = (
        await db.execute(
            select(Memory)
            .where(*base_filter, Memory.status == MemoryStatusEnum.active)
            .order_by(Memory.access_count.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    return MemoryStatsResponse(
        total_active=total_active,
        total_archived=total_archived,
        avg_importance=avg_importance,
        oldest_memory=MemoryMiniResponse.model_validate(oldest) if oldest else None,
        most_accessed_memory=MemoryMiniResponse.model_validate(most_accessed) if most_accessed else None,
    )


@router.post(
    "/agents/{agent_id}/memories/archive",
    response_model=ArchiveResponse,
    dependencies=[check_scope("memory:write")],
)
async def force_archive(
    agent_id: uuid.UUID,
    body: ArchiveRequest,
    tenant: TenantDep,
    db: DbDep,
) -> ArchiveResponse:
    """Immediately archive all active memories whose importance is below the threshold.

    Uses the tenant's ``memory_forget_threshold`` setting by default (0.05).
    Pass ``threshold`` in the request body to override for this call.
    """
    await _get_agent(agent_id, tenant.id, db)

    threshold = body.threshold
    if threshold is None:
        threshold = float(tenant.settings.get("memory_forget_threshold", 0.05))

    rows = (
        await db.execute(
            select(Memory).where(
                Memory.agent_id == agent_id,
                Memory.tenant_id == tenant.id,
                Memory.deleted_at.is_(None),
                Memory.status == MemoryStatusEnum.active,
                Memory.importance < threshold,
            )
        )
    ).scalars().all()

    for mem in rows:
        mem.status = MemoryStatusEnum.archived

    await db.commit()
    return ArchiveResponse(archived_count=len(rows))


@router.post(
    "/agents/{agent_id}/memory",
    status_code=status.HTTP_201_CREATED,
    response_model=MemoryResponse,
    dependencies=[check_scope("memory:write")],
)
async def create_memory(
    agent_id: uuid.UUID,
    body: MemoryCreateRequest,
    tenant: TenantDep,
    db: DbDep,
    redis: RedisDep,
) -> MemoryResponse:
    """Directly save a long-term memory for an agent.

    The content is embedded and deduplicated against existing memories.
    If a near-duplicate is found, Claude merges the two and soft-deletes the original.
    """
    await _get_agent(agent_id, tenant.id, db)
    lm = LongMemory(db, redis)
    mem = await lm.save(
        tenant.id,
        agent_id,
        body.content,
        importance=body.importance,
        tags=body.tags or None,
        summary=body.summary,
    )
    await db.commit()
    await db.refresh(mem)
    asyncio.create_task(
        dispatch(tenant.id, "memory.saved", {"agent_id": str(agent_id), "memory_id": str(mem.id)})
    )
    return MemoryResponse.model_validate(mem)


@router.get(
    "/agents/{agent_id}/memory",
    response_model=MemoryListResponse,
    dependencies=[check_scope("memory:read")],
)
async def list_memories(
    agent_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    include_archived: Annotated[bool, Query()] = False,
) -> MemoryListResponse:
    """List non-deleted long-term memories for an agent, paginated.

    By default only active memories are returned.  Pass
    ``include_archived=true`` to also include archived ones.
    """
    await _get_agent(agent_id, tenant.id, db)

    base = select(Memory).where(
        Memory.agent_id == agent_id,
        Memory.tenant_id == tenant.id,
        Memory.deleted_at.is_(None),
    )
    if not include_archived:
        base = base.where(Memory.status == MemoryStatusEnum.active)

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
        items=[MemoryResponse.model_validate(m) for m in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.delete(
    "/agents/{agent_id}/memory/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[check_scope("memory:write")],
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


@router.get(
    "/agents/{agent_id}/memories/{memory_id}/history",
    response_model=MemoryHistoryResponse,
    dependencies=[check_scope("memory:read")],
)
async def memory_history(
    agent_id: uuid.UUID,
    memory_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
) -> MemoryHistoryResponse:
    """Return the merge lineage of a memory as a list sorted oldest-to-newest.

    BFS through merged_from chains, including soft-deleted ancestors.
    """
    await _get_agent(agent_id, tenant.id, db)

    # Verify the root memory belongs to this agent/tenant
    root_result = await db.execute(
        select(Memory).where(
            Memory.id == memory_id,
            Memory.agent_id == agent_id,
            Memory.tenant_id == tenant.id,
        )
    )
    root = root_result.scalar_one_or_none()
    if root is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memoria no encontrada")

    # BFS to collect all ancestors (including soft-deleted)
    visited: dict[uuid.UUID, Memory] = {}
    queue: list[uuid.UUID] = list(root.merged_from)

    while queue:
        batch_ids = [mid for mid in queue if mid not in visited]
        if not batch_ids:
            break
        rows = (
            await db.execute(select(Memory).where(Memory.id.in_(batch_ids)))
        ).scalars().all()
        queue = []
        for mem in rows:
            visited[mem.id] = mem
            for parent_id in mem.merged_from:
                if parent_id not in visited:
                    queue.append(parent_id)

    lineage = sorted(visited.values(), key=lambda m: m.created_at)
    lineage.append(root)

    return MemoryHistoryResponse(
        memory_id=memory_id,
        lineage=[
            MemoryHistoryEntry(
                id=m.id,
                content=m.content,
                importance=m.importance,
                base_importance=m.base_importance,
                merged_from=m.merged_from,
                created_at=m.created_at,
                deleted_at=m.deleted_at,
            )
            for m in lineage
        ],
    )
