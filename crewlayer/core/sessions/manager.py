import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.core.agents.status import apply_status
from crewlayer.core.memory.extractor import extract_and_save
from crewlayer.core.memory.long import LongMemory
from crewlayer.core.memory.short import ShortMemory
from crewlayer.db.models import Agent, AgentStatusEnum, Session, SessionStatus


class SessionNotFoundError(Exception):
    pass


class SessionNotActiveError(Exception):
    pass


class SessionManager:
    """CRUD and lifecycle operations for conversation sessions."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        metadata: dict[str, Any] | None = None,
    ) -> Session:
        """Create a new active session and flush (caller commits).

        Also marks the agent as working and sets its current_session_id.
        """
        session = Session(
            tenant_id=tenant_id,
            agent_id=agent_id,
            metadata_=metadata or {},
        )
        self._db.add(session)
        await self._db.flush()  # get session.id

        agent_result = await self._db.execute(
            select(Agent).where(Agent.id == agent_id)
        )
        agent = agent_result.scalar_one_or_none()
        if agent is not None:
            apply_status(agent, AgentStatusEnum.working, session.id)

        await self._db.flush()
        return session

    async def get(
        self,
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> Session:
        """Return a session by ID for the given tenant.

        Raises SessionNotFoundError if not found or belongs to another tenant.
        """
        result = await self._db.execute(
            select(Session).where(
                Session.id == session_id,
                Session.tenant_id == tenant_id,
            )
        )
        sess = result.scalar_one_or_none()
        if sess is None:
            raise SessionNotFoundError(str(session_id))
        return sess

    async def close(
        self,
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
        redis: Any | None = None,
    ) -> Session:
        """Close a session: extract memories from Redis, update status, flush.

        Caller must commit, then clear ShortMemory, then dispatch webhook.
        Raises SessionNotFoundError or SessionNotActiveError when appropriate.
        """
        sess = await self.get(session_id, tenant_id)
        if sess.status != SessionStatus.active:
            raise SessionNotActiveError(str(session_id))

        agent_id = sess.agent_id
        memory_count = 0

        if redis is not None:
            sm = ShortMemory(redis)
            messages = await sm.get_messages(
                str(tenant_id), str(agent_id), str(session_id), limit=200
            )
            memory_count = len(messages)
            if messages:
                # Messages are newest-first; reverse for chronological order
                chronological = list(reversed(messages))
                conversation_lines: list[str] = []
                for msg in chronological:
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    conversation_lines.append(f"{role}: {content}")
                conversation = "\n".join(conversation_lines)

                lm = LongMemory(self._db, redis)
                await extract_and_save(tenant_id, agent_id, conversation, lm)

        sess.status = SessionStatus.closed
        sess.closed_at = datetime.now(UTC)
        sess.message_count = memory_count

        agent_result = await self._db.execute(
            select(Agent).where(Agent.id == agent_id)
        )
        agent = agent_result.scalar_one_or_none()
        if agent is not None:
            apply_status(agent, AgentStatusEnum.idle, None)

        await self._db.flush()
        return sess

    async def archive(
        self,
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> Session:
        """Archive a closed session. Raises SessionNotFoundError / SessionNotActiveError."""
        sess = await self.get(session_id, tenant_id)
        if sess.status == SessionStatus.active:
            raise SessionNotActiveError("Cannot archive an active session — close it first")
        sess.status = SessionStatus.archived
        await self._db.flush()
        return sess

    async def list(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID | None = None,
        status: SessionStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Session]:
        """List sessions for a tenant with optional agent and status filters."""
        stmt = select(Session).where(Session.tenant_id == tenant_id)
        if agent_id is not None:
            stmt = stmt.where(Session.agent_id == agent_id)
        if status is not None:
            stmt = stmt.where(Session.status == status)
        stmt = stmt.order_by(Session.started_at.desc()).offset(offset).limit(limit)
        result = await self._db.execute(stmt)
        return list(result.scalars().all())
