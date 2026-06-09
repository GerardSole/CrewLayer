import math
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.core.config import settings
from crewlayer.core.embeddings.client import get_embedding
from crewlayer.core.memory.merger import call_claude_merge, find_near_duplicate
from crewlayer.db.models import Memory, MemoryStatusEnum


class LongMemory:
    """Persistent (long-term) memory backed by PostgreSQL and pgvector.

    Provides semantic recall via cosine similarity and soft-delete via deleted_at.
    """

    def __init__(self, db: AsyncSession, redis: Any = None) -> None:
        self._db = db
        self._redis = redis

    async def save(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        content: str,
        *,
        importance: float = 0.5,
        tags: list[str] | None = None,
        summary: str | None = None,
    ) -> Memory:
        """Embed and persist a new memory, merging with any near-duplicate found.

        If an existing memory exceeds the cosine-similarity threshold (0.90), Claude
        consolidates both into a single richer memory.  The original is soft-deleted
        and the merged result carries merged_from = [original.id].
        """
        vector = await get_embedding(content, self._redis)

        duplicate = await find_near_duplicate(self._db, tenant_id, agent_id, vector)
        if duplicate is not None:
            merged_content = await call_claude_merge(duplicate.content, content)
            merged_base = max(duplicate.base_importance, importance)
            merged_tags = list({*duplicate.tags, *(tags or [])})
            merged_vector = await get_embedding(merged_content, self._redis)

            duplicate.deleted_at = datetime.now(UTC)

            merged = Memory(
                tenant_id=tenant_id,
                agent_id=agent_id,
                content=merged_content,
                embedding=merged_vector,
                importance=merged_base,
                base_importance=merged_base,
                access_count=duplicate.access_count,
                last_accessed=duplicate.last_accessed,
                tags=merged_tags,
                merged_from=[duplicate.id],
            )
            self._db.add(merged)
            await self._db.flush()
            return merged

        memory = Memory(
            tenant_id=tenant_id,
            agent_id=agent_id,
            content=content,
            summary=summary,
            embedding=vector,
            importance=importance,
            base_importance=importance,
            tags=tags or [],
        )
        self._db.add(memory)
        await self._db.flush()
        return memory

    async def recall(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        query: str,
        *,
        limit: int | None = None,
        min_similarity: float = 0.0,
    ) -> list[tuple[Memory, float]]:
        """Return top-k memories ranked by cosine similarity to the query text.

        Only non-deleted memories with an embedding are considered.
        min_similarity is in [0, 1] where 1 is identical.
        """
        if limit is None:
            limit = settings.MAX_MEMORIES_PER_RECALL

        query_vec = await get_embedding(query, self._redis)

        stmt = (
            select(
                Memory,
                (1.0 - Memory.embedding.cosine_distance(query_vec)).label("similarity"),
            )
            .where(
                Memory.tenant_id == tenant_id,
                Memory.agent_id == agent_id,
                Memory.deleted_at.is_(None),
                Memory.status == MemoryStatusEnum.active,
                Memory.embedding.isnot(None),
            )
            .order_by(Memory.embedding.cosine_distance(query_vec))
            .limit(limit)
        )
        rows = (await self._db.execute(stmt)).all()

        results = [(mem, float(sim)) for mem, sim in rows if float(sim) >= min_similarity]

        now = datetime.now(UTC)
        for mem, _ in results:
            mem.last_accessed = now
            mem.access_count = (mem.access_count or 0) + 1
            mem.importance = mem.base_importance * (
                1 + math.log(mem.access_count + 1) * 0.1
            )

        return results

    async def forget(self, memory_id: uuid.UUID, tenant_id: uuid.UUID) -> bool:
        """Soft-delete a memory. Returns False if not found or already deleted."""
        result = await self._db.execute(
            select(Memory).where(
                Memory.id == memory_id,
                Memory.tenant_id == tenant_id,
                Memory.deleted_at.is_(None),
            )
        )
        memory = result.scalar_one_or_none()
        if memory is None:
            return False
        memory.deleted_at = datetime.now(UTC)
        return True
