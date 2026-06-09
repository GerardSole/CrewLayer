"""Time-based importance decay for long-term memories.

Runs every 24 hours. Memories not accessed in more than 7 days have their
importance multiplied by 0.95 per day without access, with a floor of 0.01.

base_importance is never modified — it preserves the original score assigned
by Claude at extraction time.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.db.models import Memory

_DECAY_FACTOR = 0.95
_DECAY_THRESHOLD_DAYS = 7
_MIN_IMPORTANCE = 0.01


async def decay_importance(db: AsyncSession) -> int:
    """Apply one round of decay to memories idle for more than 7 days.

    Each call represents one 24-hour cycle. Memories whose last_accessed (or
    created_at when never accessed) is older than DECAY_THRESHOLD_DAYS receive
    a single 0.95 multiplier, clamped to MIN_IMPORTANCE.

    Returns the number of memories whose importance was updated.
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=_DECAY_THRESHOLD_DAYS)

    result = await db.execute(
        select(Memory).where(
            Memory.deleted_at.is_(None),
            Memory.importance > _MIN_IMPORTANCE,
        ).where(
            (Memory.last_accessed < cutoff)
            | (Memory.last_accessed.is_(None) & (Memory.created_at < cutoff))
        )
    )
    memories = result.scalars().all()

    updated = 0
    for mem in memories:
        new_importance = max(_MIN_IMPORTANCE, mem.importance * _DECAY_FACTOR)
        if new_importance != mem.importance:
            mem.importance = new_importance
            updated += 1

    return updated
