"""Time-based importance decay and automatic forgetting for long-term memories.

Two entry points:

``decay_importance``
    Runs every 24 h.  Memories idle for >7 days are multiplied by 0.95,
    clamped to MIN_IMPORTANCE.  base_importance is never touched.

``forget_stale_memories``
    Runs daily at 3:00 AM UTC.  Applies three rules per tenant (honoring
    per-tenant settings stored in Tenant.settings):

    Rule 1 — Hard delete:
        importance < forget_threshold  AND  last_accessed < now − delete_after_days
        → physically removed from the database.

    Rule 2 — Unaccessed decay:
        access_count == 0  AND  created_at < now − 14 days
        → importance multiplied by 0.80 (floor: MIN_IMPORTANCE).

    Rule 3 — Archive:
        importance < 0.15  AND  last_accessed < now − archive_after_days
        → status set to "archived"; excluded from normal recalls.

    Rules are applied in the order 1 → 3 → 2 so that a memory matching
    multiple rules is handled by the most severe one only.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.db.models import Memory, MemoryStatusEnum, Tenant

# ---------------------------------------------------------------------------
# Existing decay constants
# ---------------------------------------------------------------------------
_DECAY_FACTOR = 0.95
_DECAY_THRESHOLD_DAYS = 7
_MIN_IMPORTANCE = 0.01

# ---------------------------------------------------------------------------
# Forget / archive constants
# ---------------------------------------------------------------------------
_ARCHIVE_THRESHOLD = 0.15
_UNACCESSED_DECAY_FACTOR = 0.80
_UNACCESSED_DECAY_DAYS = 14


def _parse_tenant_settings(settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(settings.get("memory_decay_enabled", True)),
        "forget_threshold": float(settings.get("memory_forget_threshold", 0.05)),
        "archive_after_days": int(settings.get("memory_archive_after_days", 60)),
        "delete_after_days": int(settings.get("memory_delete_after_days", 30)),
    }


async def decay_importance(db: AsyncSession) -> int:
    """Apply one round of decay to memories idle for more than 7 days.

    Each call represents one 24-hour cycle.  Returns the number of memories
    whose importance was updated.
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=_DECAY_THRESHOLD_DAYS)

    result = await db.execute(
        select(Memory).where(
            Memory.deleted_at.is_(None),
            Memory.status == MemoryStatusEnum.active,
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


async def forget_stale_memories(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """Apply the three forgetting rules to all tenants' memories.

    Args:
        db:  Async DB session.  Caller is responsible for calling ``commit()``.
        now: Reference timestamp (defaults to UTC now).  Inject in tests to
             control relative dates without patching the system clock.

    Returns:
        Dict with keys ``hard_deleted``, ``archived``, ``decayed`` counting
        how many memories each rule affected.
    """
    if now is None:
        now = datetime.now(UTC)

    tenants = (await db.execute(select(Tenant))).scalars().all()

    hard_deleted = 0
    archived = 0
    decayed = 0

    for tenant in tenants:
        cfg = _parse_tenant_settings(tenant.settings)
        if not cfg["enabled"]:
            continue

        delete_cutoff = now - timedelta(days=cfg["delete_after_days"])
        archive_cutoff = now - timedelta(days=cfg["archive_after_days"])
        unaccessed_cutoff = now - timedelta(days=_UNACCESSED_DECAY_DAYS)

        # ----------------------------------------------------------------
        # Rule 1: Hard delete
        # importance < threshold  AND  stale
        # ----------------------------------------------------------------
        stale_for_delete = (Memory.last_accessed < delete_cutoff) | (
            Memory.last_accessed.is_(None) & (Memory.created_at < delete_cutoff)
        )
        delete_ids_q = await db.execute(
            select(Memory.id).where(
                Memory.tenant_id == tenant.id,
                Memory.deleted_at.is_(None),
                Memory.importance < cfg["forget_threshold"],
                stale_for_delete,
            )
        )
        delete_ids: set[uuid.UUID] = set(delete_ids_q.scalars().all())

        if delete_ids:
            await db.execute(delete(Memory).where(Memory.id.in_(delete_ids)))
            hard_deleted += len(delete_ids)

        # ----------------------------------------------------------------
        # Rule 3: Archive
        # importance < 0.15  AND  very stale  AND  not already being deleted
        # ----------------------------------------------------------------
        stale_for_archive = (Memory.last_accessed < archive_cutoff) | (
            Memory.last_accessed.is_(None) & (Memory.created_at < archive_cutoff)
        )
        archive_where = [
            Memory.tenant_id == tenant.id,
            Memory.deleted_at.is_(None),
            Memory.status == MemoryStatusEnum.active,
            Memory.importance < _ARCHIVE_THRESHOLD,
            stale_for_archive,
        ]
        if delete_ids:
            archive_where.append(Memory.id.not_in(delete_ids))

        archive_ids_q = await db.execute(select(Memory.id).where(*archive_where))
        archive_ids: set[uuid.UUID] = set(archive_ids_q.scalars().all())

        if archive_ids:
            await db.execute(
                update(Memory)
                .where(Memory.id.in_(archive_ids))
                .values(status=MemoryStatusEnum.archived)
            )
            archived += len(archive_ids)

        # ----------------------------------------------------------------
        # Rule 2: Unaccessed decay
        # access_count == 0  AND  old  AND  not already handled above
        # ----------------------------------------------------------------
        excluded = delete_ids | archive_ids
        decay_where = [
            Memory.tenant_id == tenant.id,
            Memory.deleted_at.is_(None),
            Memory.status == MemoryStatusEnum.active,
            Memory.access_count == 0,
            Memory.created_at < unaccessed_cutoff,
        ]
        if excluded:
            decay_where.append(Memory.id.not_in(excluded))

        decay_ids_q = await db.execute(select(Memory.id).where(*decay_where))
        decay_ids: set[uuid.UUID] = set(decay_ids_q.scalars().all())

        if decay_ids:
            await db.execute(
                update(Memory)
                .where(Memory.id.in_(decay_ids))
                .values(
                    importance=func.greatest(
                        _MIN_IMPORTANCE,
                        Memory.importance * _UNACCESSED_DECAY_FACTOR,
                    )
                )
            )
            decayed += len(decay_ids)

    return {"hard_deleted": hard_deleted, "archived": archived, "decayed": decayed}
