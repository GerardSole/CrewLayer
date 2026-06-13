import uuid
from datetime import UTC, datetime
from typing import Any

import anthropic
from anthropic.types import TextBlock as _TextBlock
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.core.embeddings.client import get_embedding
from crewlayer.db.models import (
    Episode,
    EpisodeMemory,
    EpisodeStatusEnum,
    Memory,
    MemoryStatusEnum,
    Session,
)

# Module-level client so tests can patch crewlayer.core.memory.episodic._client
_client = anthropic.AsyncAnthropic()

_SUMMARY_SYSTEM = """\
You are an episode summarization assistant. Given the title and memories of a completed task episode, \
produce a concise summary that captures the key events, decisions, facts, and outcomes.
Respond with only the summary text — no headers, no lists, no markdown.
"""


class EpisodeNotFoundError(Exception):
    pass


class SessionNotFoundError(Exception):
    pass


class EpisodicMemory:
    """Groups long-term memories under named episodes spanning one or more sessions."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create_episode(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        title: str,
        *,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Episode:
        episode = Episode(
            tenant_id=tenant_id,
            agent_id=agent_id,
            title=title,
            description=description,
            metadata_=metadata or {},
        )
        self._db.add(episode)
        await self._db.flush()
        return episode

    async def add_session_to_episode(
        self,
        tenant_id: uuid.UUID,
        episode_id: uuid.UUID,
        session_id: uuid.UUID,
    ) -> Episode:
        """Link a session to an episode and auto-discover memories from its time window."""
        ep = await self._load_episode(episode_id, tenant_id)

        sess_result = await self._db.execute(
            select(Session).where(Session.id == session_id, Session.tenant_id == tenant_id)
        )
        sess = sess_result.scalar_one_or_none()
        if sess is None:
            raise SessionNotFoundError(session_id)

        sess.episode_id = episode_id

        # Discover memories created during the session's time window
        end_time = sess.closed_at or datetime.now(UTC)
        mem_result = await self._db.execute(
            select(Memory).where(
                Memory.tenant_id == tenant_id,
                Memory.agent_id == sess.agent_id,
                Memory.deleted_at.is_(None),
                Memory.created_at >= sess.started_at,
                Memory.created_at <= end_time,
            )
        )
        for mem in mem_result.scalars().all():
            existing = await self._db.execute(
                select(EpisodeMemory).where(
                    EpisodeMemory.episode_id == episode_id,
                    EpisodeMemory.memory_id == mem.id,
                )
            )
            if existing.scalar_one_or_none() is None:
                self._db.add(EpisodeMemory(episode_id=episode_id, memory_id=mem.id))

        await self._db.flush()
        return ep

    async def complete_episode(
        self,
        tenant_id: uuid.UUID,
        episode_id: uuid.UUID,
    ) -> Episode:
        """Mark episode completed and generate an AI summary from its memories."""
        ep = await self._load_episode(episode_id, tenant_id)

        mem_result = await self._db.execute(
            select(Memory)
            .join(EpisodeMemory, EpisodeMemory.memory_id == Memory.id)
            .where(EpisodeMemory.episode_id == episode_id, Memory.deleted_at.is_(None))
        )
        memories = list(mem_result.scalars().all())

        summary = await _generate_summary(ep.title, memories)

        ep.status = EpisodeStatusEnum.completed
        ep.completed_at = datetime.now(UTC)
        ep.summary = summary
        await self._db.flush()
        return ep

    async def recall_episode(
        self,
        tenant_id: uuid.UUID,
        episode_id: uuid.UUID,
        query: str,
        *,
        limit: int = 10,
        min_similarity: float = 0.0,
        redis: Any = None,
    ) -> list[tuple[Memory, float]]:
        """Semantic search restricted to the memories associated with this episode."""
        query_vec = await get_embedding(query, redis)

        stmt = (
            select(
                Memory,
                (1.0 - Memory.embedding.cosine_distance(query_vec)).label("similarity"),
            )
            .join(EpisodeMemory, EpisodeMemory.memory_id == Memory.id)
            .where(
                EpisodeMemory.episode_id == episode_id,
                Memory.tenant_id == tenant_id,
                Memory.deleted_at.is_(None),
                Memory.status == MemoryStatusEnum.active,
                Memory.embedding.isnot(None),
            )
            .order_by(Memory.embedding.cosine_distance(query_vec))
            .limit(limit)
        )
        rows = (await self._db.execute(stmt)).all()
        return [(mem, float(sim)) for mem, sim in rows if float(sim) >= min_similarity]

    async def get_episode_sessions(self, episode_id: uuid.UUID) -> list[Session]:
        result = await self._db.execute(
            select(Session).where(Session.episode_id == episode_id)
        )
        return list(result.scalars().all())

    async def get_episode_memories(self, episode_id: uuid.UUID) -> list[Memory]:
        result = await self._db.execute(
            select(Memory)
            .join(EpisodeMemory, EpisodeMemory.memory_id == Memory.id)
            .where(EpisodeMemory.episode_id == episode_id, Memory.deleted_at.is_(None))
        )
        return list(result.scalars().all())

    async def _load_episode(self, episode_id: uuid.UUID, tenant_id: uuid.UUID) -> Episode:
        result = await self._db.execute(
            select(Episode).where(Episode.id == episode_id, Episode.tenant_id == tenant_id)
        )
        ep = result.scalar_one_or_none()
        if ep is None:
            raise EpisodeNotFoundError(episode_id)
        return ep


async def _generate_summary(title: str, memories: list[Memory]) -> str:
    if not memories:
        return f"Episode '{title}' completed with no associated memories."

    memory_text = "\n".join(
        f"- {m.content}" for m in memories
    )
    prompt = f"Episode title: {title}\n\nMemories:\n{memory_text}"

    response = await _client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1024,
        system=_SUMMARY_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    block = response.content[0]
    return block.text if isinstance(block, _TextBlock) else ""
