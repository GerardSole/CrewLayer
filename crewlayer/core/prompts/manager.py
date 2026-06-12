"""Prompt version control manager.

Handles creation, activation, rollback and diffing of agent system prompts.
All mutations that touch is_active are transactional to guarantee exactly one
active version per agent at any time.
"""
from __future__ import annotations

import difflib
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.db.models import PromptVersion


@dataclass
class DiffLine:
    operation: str   # "equal" | "insert" | "delete"
    content: str
    line_a: int | None = None
    line_b: int | None = None


class PromptNotFoundError(Exception):
    pass


class NoActiveVersionError(Exception):
    pass


class NoPreviousVersionError(Exception):
    pass


class PromptManager:
    """Business logic for prompt version control."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def _get_version(
        self, tenant_id: uuid.UUID, version_id: uuid.UUID
    ) -> PromptVersion:
        result = await self._db.execute(
            select(PromptVersion).where(
                PromptVersion.id == version_id,
                PromptVersion.tenant_id == tenant_id,
            )
        )
        pv = result.scalar_one_or_none()
        if pv is None:
            raise PromptNotFoundError(f"Prompt version {version_id} not found")
        return pv

    async def get_active(
        self, tenant_id: uuid.UUID, agent_id: uuid.UUID
    ) -> PromptVersion | None:
        """Return the currently active version, or None if none is set."""
        result = await self._db.execute(
            select(PromptVersion).where(
                PromptVersion.tenant_id == tenant_id,
                PromptVersion.agent_id == agent_id,
                PromptVersion.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def list_versions(
        self, tenant_id: uuid.UUID, agent_id: uuid.UUID
    ) -> list[PromptVersion]:
        """Return all versions for an agent, newest first."""
        result = await self._db.execute(
            select(PromptVersion)
            .where(
                PromptVersion.tenant_id == tenant_id,
                PromptVersion.agent_id == agent_id,
            )
            .order_by(PromptVersion.version.desc())
        )
        return list(result.scalars().all())

    async def get_version_detail(
        self, tenant_id: uuid.UUID, version_id: uuid.UUID
    ) -> PromptVersion:
        return await self._get_version(tenant_id, version_id)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    async def create_version(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        content: str,
        description: str | None = None,
        created_by: uuid.UUID | None = None,
    ) -> PromptVersion:
        """Create a new version with auto-incremented version number."""
        max_result = await self._db.execute(
            select(func.max(PromptVersion.version)).where(
                PromptVersion.tenant_id == tenant_id,
                PromptVersion.agent_id == agent_id,
            )
        )
        current_max: int | None = max_result.scalar()
        next_version = (current_max or 0) + 1

        pv = PromptVersion(
            tenant_id=tenant_id,
            agent_id=agent_id,
            version=next_version,
            content=content,
            description=description,
            is_active=False,
            created_by=created_by,
        )
        self._db.add(pv)
        await self._db.flush()
        return pv

    async def activate(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        version_id: uuid.UUID,
    ) -> PromptVersion:
        """Activate a version — deactivates any currently active version atomically."""
        target = await self._get_version(tenant_id, version_id)
        if target.agent_id != agent_id:
            raise PromptNotFoundError(f"Prompt version {version_id} not found")

        # Deactivate all versions for this agent in one UPDATE
        await self._db.execute(
            update(PromptVersion)
            .where(
                PromptVersion.tenant_id == tenant_id,
                PromptVersion.agent_id == agent_id,
            )
            .values(is_active=False)
        )
        target.is_active = True
        await self._db.flush()
        return target

    async def rollback(
        self, tenant_id: uuid.UUID, agent_id: uuid.UUID
    ) -> PromptVersion:
        """Activate the version immediately before the currently active one.

        'Immediately before' means the highest version number that is strictly
        less than the active version's number.
        """
        active = await self.get_active(tenant_id, agent_id)
        if active is None:
            raise NoActiveVersionError("No active version to roll back from")

        result = await self._db.execute(
            select(PromptVersion)
            .where(
                PromptVersion.tenant_id == tenant_id,
                PromptVersion.agent_id == agent_id,
                PromptVersion.version < active.version,
            )
            .order_by(PromptVersion.version.desc())
            .limit(1)
        )
        previous = result.scalar_one_or_none()
        if previous is None:
            raise NoPreviousVersionError("No previous version available for rollback")

        return await self.activate(tenant_id, agent_id, previous.id)

    # ------------------------------------------------------------------
    # Diff
    # ------------------------------------------------------------------

    async def diff(
        self,
        tenant_id: uuid.UUID,
        version_id_a: uuid.UUID,
        version_id_b: uuid.UUID,
    ) -> list[DiffLine]:
        """Return a line-by-line unified diff between two versions."""
        pv_a = await self._get_version(tenant_id, version_id_a)
        pv_b = await self._get_version(tenant_id, version_id_b)

        lines_a = pv_a.content.splitlines(keepends=True)
        lines_b = pv_b.content.splitlines(keepends=True)

        matcher = difflib.SequenceMatcher(None, lines_a, lines_b)
        result: list[DiffLine] = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for k, line in enumerate(lines_a[i1:i2]):
                    result.append(DiffLine("equal", line.rstrip("\n"), i1 + k + 1, j1 + k + 1))
            elif tag == "replace":
                for k, line in enumerate(lines_a[i1:i2]):
                    result.append(DiffLine("delete", line.rstrip("\n"), i1 + k + 1, None))
                for k, line in enumerate(lines_b[j1:j2]):
                    result.append(DiffLine("insert", line.rstrip("\n"), None, j1 + k + 1))
            elif tag == "delete":
                for k, line in enumerate(lines_a[i1:i2]):
                    result.append(DiffLine("delete", line.rstrip("\n"), i1 + k + 1, None))
            elif tag == "insert":
                for k, line in enumerate(lines_b[j1:j2]):
                    result.append(DiffLine("insert", line.rstrip("\n"), None, j1 + k + 1))
        return result
