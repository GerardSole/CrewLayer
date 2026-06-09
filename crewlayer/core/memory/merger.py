"""Duplicate detection and Claude-powered merging for long-term memories.

Before a new memory is persisted, find_near_duplicate() checks for an existing
memory whose cosine similarity to the incoming embedding exceeds MERGE_THRESHOLD.
When found, call_claude_merge() asks claude-opus-4-8 to consolidate the two into
a single richer memory.
"""

import uuid
from typing import cast

import anthropic
from anthropic.types import TextBlock
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.db.models import Memory

MERGE_THRESHOLD = 0.90

# Module-level client so tests can patch crewlayer.core.memory.merger._client
_client = anthropic.AsyncAnthropic()

_MERGE_SYSTEM = """\
You are a memory consolidation assistant. You will receive two memory entries that cover overlapping
information. Produce a single, more complete merged memory that captures all important facts from both,
without duplication.

Respond ONLY with the text of the merged memory — no explanation, no markdown fences, just the merged text.
"""


async def find_near_duplicate(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    embedding: list[float],
    threshold: float = MERGE_THRESHOLD,
) -> Memory | None:
    """Return the closest existing (non-deleted) memory if its similarity exceeds threshold.

    Uses cosine similarity via pgvector. Returns None when no memory meets the threshold
    or when there are no existing memories to compare against.
    """
    stmt = (
        select(
            Memory,
            (1.0 - Memory.embedding.cosine_distance(embedding)).label("sim"),
        )
        .where(
            Memory.tenant_id == tenant_id,
            Memory.agent_id == agent_id,
            Memory.deleted_at.is_(None),
            Memory.embedding.isnot(None),
        )
        .order_by(Memory.embedding.cosine_distance(embedding))
        .limit(1)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        return None
    mem, sim = row
    return mem if float(sim) >= threshold else None


async def call_claude_merge(existing_content: str, incoming_content: str) -> str:
    """Ask claude-opus-4-8 to produce a single merged text from two overlapping memories.

    Returns the raw merged text as a plain string.
    """
    prompt = f"Memory 1:\n{existing_content}\n\nMemory 2:\n{incoming_content}"
    response = await _client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1024,
        system=_MERGE_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return cast(TextBlock, response.content[0]).text.strip()
