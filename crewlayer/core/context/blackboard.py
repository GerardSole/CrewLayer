import asyncio
import json
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.db.models import ContextEntry


class VersionConflictError(Exception):
    """Raised when the caller's expected_version doesn't match the stored version."""

    def __init__(self, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"Version conflict: expected {expected}, got {actual}")


async def _publish_context_event(
    redis: Redis,
    tenant_id: uuid.UUID,
    namespace: str,
    key: str,
    *,
    value: dict[str, Any] | None,
    version: int,
    written_by: uuid.UUID | None,
    event: str,
) -> None:
    """Publish a context change to the Redis channel for this key."""
    channel = f"context:{tenant_id}:{namespace}:{key}"
    payload = json.dumps({
        "key": key,
        "value": value,
        "version": version,
        "written_by": str(written_by) if written_by else None,
        "event": event,
    })
    with suppress(Exception):
        await redis.publish(channel, payload)


class Blackboard:
    """Shared key-value store for multi-agent communication within a tenant.

    Namespace isolation: keys are scoped to (tenant_id, namespace, key).
    Optimistic locking: callers may pass expected_version; a mismatch raises
    VersionConflictError. Version is always incremented on each successful write.

    When a Redis client is supplied, write() and delete() publish change events
    to channel ``context:{tenant_id}:{namespace}:{key}`` as fire-and-forget tasks.
    """

    def __init__(self, db: AsyncSession, redis: Redis | None = None) -> None:
        self._db = db
        self._redis = redis

    async def write(
        self,
        tenant_id: uuid.UUID,
        namespace: str,
        key: str,
        value: dict[str, Any],
        *,
        written_by: uuid.UUID | None = None,
        expires_at: datetime | None = None,
        expected_version: int | None = None,
    ) -> ContextEntry:
        """Upsert a context entry with optimistic locking.

        If expected_version is provided it must match the current version
        (or be 0 / None for a brand-new key). On mismatch raises VersionConflictError.
        Caller must commit after this returns.
        """
        result = await self._db.execute(
            select(ContextEntry).where(
                ContextEntry.tenant_id == tenant_id,
                ContextEntry.namespace == namespace,
                ContextEntry.key == key,
            )
        )
        entry = result.scalar_one_or_none()

        if entry is None:
            if expected_version is not None and expected_version != 0:
                raise VersionConflictError(expected=expected_version, actual=0)
            entry = ContextEntry(
                tenant_id=tenant_id,
                namespace=namespace,
                key=key,
                value=value,
                written_by=written_by,
                expires_at=expires_at,
                version=1,
            )
            self._db.add(entry)
        else:
            if expected_version is not None and entry.version != expected_version:
                raise VersionConflictError(expected=expected_version, actual=entry.version)
            entry.value = value
            entry.written_by = written_by
            entry.expires_at = expires_at
            entry.version += 1

        await self._db.flush()

        if self._redis is not None:
            asyncio.create_task(
                _publish_context_event(
                    self._redis,
                    tenant_id,
                    namespace,
                    key,
                    value=dict(entry.value),
                    version=entry.version,
                    written_by=written_by,
                    event="updated",
                )
            )

        return entry

    async def read(
        self,
        tenant_id: uuid.UUID,
        namespace: str,
        key: str,
    ) -> ContextEntry | None:
        """Return the entry, or None if absent or expired."""
        result = await self._db.execute(
            select(ContextEntry).where(
                ContextEntry.tenant_id == tenant_id,
                ContextEntry.namespace == namespace,
                ContextEntry.key == key,
            )
        )
        entry = result.scalar_one_or_none()
        if entry is None:
            return None
        if entry.expires_at is not None:
            exp = entry.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=UTC)
            if exp < datetime.now(UTC):
                return None
        return entry

    async def list_namespace(
        self,
        tenant_id: uuid.UUID,
        namespace: str,
    ) -> list[ContextEntry]:
        """Return all non-expired entries in a namespace, ordered by key."""
        now = datetime.now(UTC)
        result = await self._db.execute(
            select(ContextEntry).where(
                ContextEntry.tenant_id == tenant_id,
                ContextEntry.namespace == namespace,
                (ContextEntry.expires_at.is_(None))
                | (ContextEntry.expires_at > now),
            ).order_by(ContextEntry.key)
        )
        return list(result.scalars().all())

    async def delete(
        self,
        tenant_id: uuid.UUID,
        namespace: str,
        key: str,
    ) -> bool:
        """Delete an entry. Returns False if it did not exist."""
        result = await self._db.execute(
            delete(ContextEntry).where(
                ContextEntry.tenant_id == tenant_id,
                ContextEntry.namespace == namespace,
                ContextEntry.key == key,
            )
        )
        deleted: bool = result.rowcount > 0  # type: ignore[attr-defined]

        if deleted and self._redis is not None:
            asyncio.create_task(
                _publish_context_event(
                    self._redis,
                    tenant_id,
                    namespace,
                    key,
                    value=None,
                    version=0,
                    written_by=None,
                    event="deleted",
                )
            )

        return deleted


async def cleanup_expired(db: AsyncSession) -> int:
    """Remove all expired ContextEntry rows. Returns the count deleted."""
    result = await db.execute(
        delete(ContextEntry).where(
            ContextEntry.expires_at.isnot(None),
            ContextEntry.expires_at < datetime.now(UTC),
        )
    )
    await db.commit()
    return result.rowcount  # type: ignore[attr-defined, no-any-return]
