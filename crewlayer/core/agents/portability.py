"""Agent portability: export to JSON and import from JSON.

Export streams data section-by-section (memories and actions use server-side cursors).
Import runs in a single savepoint for atomicity; embeddings are regenerated in background.
"""
import asyncio
import json
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, field_validator
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.core.embeddings.client import get_embedding
from crewlayer.db.models import (
    Action,
    ActionStatus,
    Agent,
    AgentRelation,
    Episode,
    EpisodeMemory,
    EpisodeStatusEnum,
    Memory,
    MemoryStatusEnum,
    Session,
    SessionStatus,
)
from crewlayer.db.session import AsyncSessionLocal

EXPORT_VERSION = "1.0"
_SUPPORTED_VERSIONS = {"1.0"}
_ACTION_DAYS = 90


# ---------------------------------------------------------------------------
# Pydantic validation models for import
# ---------------------------------------------------------------------------

class _AgentFields(BaseModel):
    name: str
    description: str | None = None
    config: dict[str, Any] = {}
    tags: list[str] = []
    created_at: str = ""


class _MemoryFields(BaseModel):
    id: str
    content: str
    importance: float = 0.5
    base_importance: float = 0.5
    embedding: list[float] | None = None
    tags: list[str] = []
    merged_from: list[str] = []
    status: str = "active"
    created_at: str = ""
    last_accessed: str | None = None
    access_count: int = 0


class _ActionFields(BaseModel):
    id: str
    session_id: str | None = None
    tool_name: str
    input_params: dict[str, Any] = {}
    output_result: dict[str, Any] = {}
    status: str
    duration_ms: int | None = None
    error_msg: str | None = None
    timestamp: str = ""
    metadata: dict[str, Any] = {}


class _EpisodeFields(BaseModel):
    id: str
    title: str
    description: str | None = None
    status: str = "active"
    summary: str | None = None
    started_at: str = ""
    completed_at: str | None = None
    metadata: dict[str, Any] = {}


class _SessionFields(BaseModel):
    id: str
    episode_id: str | None = None
    status: str
    summary: str | None = None
    message_count: int = 0
    started_at: str = ""
    closed_at: str | None = None
    metadata: dict[str, Any] = {}


class _EpisodeMemoryLink(BaseModel):
    episode_id: str
    memory_id: str


class _RelationFields(BaseModel):
    supervisor_id: str
    subordinate_id: str
    relation_type: str


class AgentExportData(BaseModel):
    """Validated schema for an agent export document."""
    export_version: str
    exported_at: str = ""
    source_agent_id: str = ""
    source_tenant_id: str = ""
    agent: _AgentFields
    memories: list[_MemoryFields] = []
    actions: list[_ActionFields] = []
    episodes: list[_EpisodeFields] = []
    sessions: list[_SessionFields] = []
    episode_memories: list[_EpisodeMemoryLink] = []
    relations: list[_RelationFields] = []

    @field_validator("export_version")
    @classmethod
    def _check_version(cls, v: str) -> str:
        if v not in _SUPPORTED_VERSIONS:
            raise ValueError(
                f"export_version '{v}' is not supported. Supported: {sorted(_SUPPORTED_VERSIONS)}"
            )
        return v


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso(val: datetime | None) -> str | None:
    if val is None:
        return None
    if val.tzinfo is None:
        val = val.replace(tzinfo=UTC)
    return val.isoformat()


def _parse_dt(val: str | None) -> datetime | None:
    if not val:
        return None
    try:
        return datetime.fromisoformat(val)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Export — async generator (streams section-by-section)
# ---------------------------------------------------------------------------

async def stream_export_agent(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
) -> AsyncGenerator[bytes, None]:
    """Yield the agent export as UTF-8 JSON bytes, section by section.

    Memories and actions are streamed with server-side cursors to avoid
    loading all vectors into memory at once.
    """
    # Validate agent exists before we start yielding
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id)
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise ValueError(f"Agent {agent_id} not found in tenant {tenant_id}")

    # --- Header (everything except the last closing brace) ---
    header: dict[str, Any] = {
        "export_version": EXPORT_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "source_agent_id": str(agent_id),
        "source_tenant_id": str(tenant_id),
        "agent": {
            "name": agent.name,
            "description": agent.description,
            "config": agent.config,
            "tags": list(agent.tags or []),
            "created_at": _iso(agent.created_at),
        },
    }
    # Yield opening: {"export_version":..., "agent":{...},   (no closing brace)
    yield (json.dumps(header, default=str)[:-1] + ",").encode()

    # --- Memories (server-side cursor) ---
    yield b'"memories":['
    first = True
    async for mem in await db.stream_scalars(
        select(Memory).where(
            Memory.tenant_id == tenant_id,
            Memory.agent_id == agent_id,
            Memory.deleted_at.is_(None),
        )
    ):
        chunk = json.dumps({
            "id": str(mem.id),
            "content": mem.content,
            "importance": mem.importance,
            "base_importance": mem.base_importance,
            "embedding": [float(x) for x in mem.embedding] if mem.embedding is not None else None,
            "tags": list(mem.tags or []),
            "merged_from": [str(x) for x in (mem.merged_from or [])],
            "status": mem.status.value,
            "created_at": _iso(mem.created_at),
            "last_accessed": _iso(mem.last_accessed),
            "access_count": mem.access_count,
        })
        if not first:
            yield b","
        first = False
        yield chunk.encode()
    yield b"]"

    # --- Actions (server-side cursor, last 90 days) ---
    cutoff = datetime.now(UTC) - timedelta(days=_ACTION_DAYS)
    yield b',"actions":['
    first = True
    async for act in await db.stream_scalars(
        select(Action).where(
            Action.tenant_id == tenant_id,
            Action.agent_id == agent_id,
            Action.timestamp >= cutoff,
        ).order_by(Action.timestamp)
    ):
        chunk = json.dumps({
            "id": str(act.id),
            "session_id": str(act.session_id) if act.session_id else None,
            "tool_name": act.tool_name,
            "input_params": act.input_params,
            "output_result": act.output_result,
            "status": act.status.value,
            "duration_ms": act.duration_ms,
            "error_msg": act.error_msg,
            "timestamp": _iso(act.timestamp),
            "metadata": act.metadata_,
        })
        if not first:
            yield b","
        first = False
        yield chunk.encode()
    yield b"]"

    # --- Episodes (load all; typically small) ---
    ep_rows = list((await db.execute(
        select(Episode).where(Episode.tenant_id == tenant_id, Episode.agent_id == agent_id)
    )).scalars().all())
    episode_ids = {ep.id for ep in ep_rows}

    yield b',"episodes":' + json.dumps([
        {
            "id": str(ep.id),
            "title": ep.title,
            "description": ep.description,
            "status": ep.status.value,
            "summary": ep.summary,
            "started_at": _iso(ep.started_at),
            "completed_at": _iso(ep.completed_at),
            "metadata": ep.metadata_,
        }
        for ep in ep_rows
    ], default=str).encode()

    # --- Closed sessions ---
    sess_rows = list((await db.execute(
        select(Session).where(
            Session.tenant_id == tenant_id,
            Session.agent_id == agent_id,
            Session.status != SessionStatus.active,
        )
    )).scalars().all())

    yield b',"sessions":' + json.dumps([
        {
            "id": str(s.id),
            "episode_id": str(s.episode_id) if s.episode_id else None,
            "status": s.status.value,
            "summary": s.summary,
            "message_count": s.message_count,
            "started_at": _iso(s.started_at),
            "closed_at": _iso(s.closed_at),
            "metadata": s.metadata_,
        }
        for s in sess_rows
    ], default=str).encode()

    # --- Episode-memory links ---
    if episode_ids:
        em_rows = list((await db.execute(
            select(EpisodeMemory).where(EpisodeMemory.episode_id.in_(episode_ids))
        )).scalars().all())
    else:
        em_rows = []

    yield b',"episode_memories":' + json.dumps([
        {"episode_id": str(em.episode_id), "memory_id": str(em.memory_id)}
        for em in em_rows
    ]).encode()

    # --- Relations ---
    rel_rows = list((await db.execute(
        select(AgentRelation).where(
            AgentRelation.tenant_id == tenant_id,
            or_(
                AgentRelation.supervisor_id == agent_id,
                AgentRelation.subordinate_id == agent_id,
            ),
        )
    )).scalars().all())

    yield b',"relations":' + json.dumps([
        {
            "supervisor_id": str(r.supervisor_id),
            "subordinate_id": str(r.subordinate_id),
            "relation_type": r.relation_type.value,
        }
        for r in rel_rows
    ]).encode()

    yield b"}"


async def export_agent(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
) -> dict[str, Any]:
    """Collect the full export into a dict (used internally / in tests)."""
    chunks: list[bytes] = []
    async for chunk in stream_export_agent(db, tenant_id, agent_id):
        chunks.append(chunk)
    return json.loads(b"".join(chunks))  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

async def import_agent(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: AgentExportData,
) -> tuple[Agent, dict[str, dict[str, str]], list[uuid.UUID]]:
    """Restore an exported agent as a new agent under tenant_id.

    Returns (new_agent, id_map, new_memory_ids).
    id_map maps old UUID strings → new UUID strings for memories, actions,
    episodes, and sessions.
    Caller must wrap this in begin_nested() and commit afterwards.
    """
    id_map: dict[str, dict[str, str]] = {
        "memories": {},
        "actions": {},
        "episodes": {},
        "sessions": {},
    }

    # 1. Create agent
    new_agent = Agent(
        tenant_id=tenant_id,
        name=data.agent.name,
        description=data.agent.description,
        config=data.agent.config,
        tags=list(data.agent.tags),
    )
    db.add(new_agent)
    await db.flush()

    # 2. Import episodes first (sessions reference them)
    for ep in data.episodes:
        new_ep = Episode(
            tenant_id=tenant_id,
            agent_id=new_agent.id,
            title=ep.title,
            description=ep.description,
            status=EpisodeStatusEnum(ep.status) if ep.status else EpisodeStatusEnum.active,
            summary=ep.summary,
            started_at=_parse_dt(ep.started_at) or datetime.now(UTC),
            completed_at=_parse_dt(ep.completed_at),
            metadata_=ep.metadata,
        )
        db.add(new_ep)
        await db.flush()
        id_map["episodes"][ep.id] = str(new_ep.id)

    # 3. Import sessions
    for sess in data.sessions:
        old_ep_id = sess.episode_id
        new_ep_id_str = id_map["episodes"].get(old_ep_id) if old_ep_id else None
        new_sess = Session(
            tenant_id=tenant_id,
            agent_id=new_agent.id,
            episode_id=uuid.UUID(new_ep_id_str) if new_ep_id_str else None,
            status=SessionStatus(sess.status),
            summary=sess.summary,
            message_count=sess.message_count,
            started_at=_parse_dt(sess.started_at) or datetime.now(UTC),
            closed_at=_parse_dt(sess.closed_at),
            metadata_=sess.metadata,
        )
        db.add(new_sess)
        await db.flush()
        id_map["sessions"][sess.id] = str(new_sess.id)

    # 4. Import memories (keep exported embeddings; regenerated in background)
    new_memory_ids: list[uuid.UUID] = []
    for mem in data.memories:
        new_mem = Memory(
            tenant_id=tenant_id,
            agent_id=new_agent.id,
            content=mem.content,
            embedding=mem.embedding,
            importance=mem.importance,
            base_importance=mem.base_importance,
            access_count=mem.access_count,
            tags=list(mem.tags),
            merged_from=[],  # old IDs no longer valid in the new tenant
            status=MemoryStatusEnum(mem.status) if mem.status else MemoryStatusEnum.active,
            last_accessed=_parse_dt(mem.last_accessed),
        )
        db.add(new_mem)
        await db.flush()
        id_map["memories"][mem.id] = str(new_mem.id)
        new_memory_ids.append(new_mem.id)

    # 5. Import actions
    for act in data.actions:
        old_sid = act.session_id
        new_sid_str = id_map["sessions"].get(old_sid) if old_sid else None
        new_act = Action(
            tenant_id=tenant_id,
            agent_id=new_agent.id,
            session_id=uuid.UUID(new_sid_str) if new_sid_str else None,
            tool_name=act.tool_name,
            input_params=act.input_params,
            output_result=act.output_result,
            status=ActionStatus(act.status),
            duration_ms=act.duration_ms,
            error_msg=act.error_msg,
            metadata_=act.metadata,
        )
        db.add(new_act)
        id_map["actions"][act.id] = str(new_act.id)
    if data.actions:
        await db.flush()

    # 6. Episode-memory links
    for em in data.episode_memories:
        new_ep_id_str = id_map["episodes"].get(em.episode_id)
        new_mem_id_str = id_map["memories"].get(em.memory_id)
        if new_ep_id_str and new_mem_id_str:
            db.add(EpisodeMemory(
                episode_id=uuid.UUID(new_ep_id_str),
                memory_id=uuid.UUID(new_mem_id_str),
            ))
    if data.episode_memories:
        await db.flush()

    # Relations are exported for reference but not restored
    # (referenced agents may not exist in the target environment)

    return new_agent, id_map, new_memory_ids


# ---------------------------------------------------------------------------
# Background embedding regeneration
# ---------------------------------------------------------------------------

async def regenerate_embeddings_background(memory_ids: list[uuid.UUID]) -> None:
    """Re-compute embeddings for imported memories using the live embedding service."""
    if not memory_ids:
        return
    async with AsyncSessionLocal() as db:
        for mem_id in memory_ids:
            try:
                result = await db.execute(select(Memory).where(Memory.id == mem_id))
                mem = result.scalar_one_or_none()
                if mem is None:
                    continue
                embedding = await get_embedding(mem.content)
                mem.embedding = embedding
                await db.flush()
            except Exception:
                pass
        try:
            await db.commit()
        except Exception:
            pass
