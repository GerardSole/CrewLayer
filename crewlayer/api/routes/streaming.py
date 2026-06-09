"""SSE streaming endpoint for real-time session message delivery.

GET /v1/agents/{agent_id}/sessions/{session_id}/stream

Emits three SSE event types:
  message          — a new short-memory message was appended to the session
  memory_extracted — memories were extracted (fires when the session closes)
  heartbeat        — keepalive every 30 s

The stream terminates cleanly when a session_closed or session_archived event
is received from the Redis Pub/Sub channel, or when the client disconnects.
"""

import asyncio
import contextlib
import json
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse, ServerSentEvent  # type: ignore[attr-defined]

from crewlayer.api.deps import DbDep, RedisDep, TenantDep, check_scope
from crewlayer.core.streaming.broker import make_channel
from crewlayer.db.models import Agent, Session, SessionStatus

router = APIRouter()

_HEARTBEAT_INTERVAL = 30.0  # seconds
_TERMINAL_EVENTS = frozenset({"session_closed", "session_archived"})


async def _get_session(
    agent_id: uuid.UUID,
    session_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> Session:
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agente no encontrado")

    result2 = await db.execute(
        select(Session).where(
            Session.id == session_id,
            Session.agent_id == agent_id,
            Session.tenant_id == tenant_id,
        )
    )
    sess = result2.scalar_one_or_none()
    if sess is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sesión no encontrada")
    return sess


@router.get("/agents/{agent_id}/sessions/{session_id}/stream", dependencies=[check_scope("sessions:read")])
async def stream_session(
    agent_id: uuid.UUID,
    session_id: uuid.UUID,
    request: Request,
    tenant: TenantDep,
    db: DbDep,
    redis: RedisDep,
) -> EventSourceResponse:
    """Open a Server-Sent Events stream for a live session.

    Yields message, memory_extracted, and heartbeat events.
    Terminates when the session closes/archives or the client disconnects.
    """
    sess = await _get_session(agent_id, session_id, tenant.id, db)

    if sess.status != SessionStatus.active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La sesión no está activa",
        )

    channel = make_channel(tenant.id, agent_id, session_id)

    async def event_generator() -> AsyncGenerator[ServerSentEvent, None]:
        queue: asyncio.Queue[str] = asyncio.Queue()

        async def _pump() -> None:
            """Subscribe to Redis Pub/Sub and forward messages to the queue."""
            ps = redis.pubsub()
            await ps.subscribe(channel)
            try:
                async for msg in ps.listen():
                    if msg["type"] == "message":
                        await queue.put(str(msg["data"]))
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            finally:
                with contextlib.suppress(Exception):
                    await ps.unsubscribe(channel)
                with contextlib.suppress(Exception):
                    await ps.aclose()  # type: ignore[no-untyped-call]

        pump_task = asyncio.create_task(_pump())

        try:
            while True:
                if await request.is_disconnected():
                    break

                try:
                    raw = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_INTERVAL)
                except asyncio.TimeoutError:
                    # Client still connected; emit keepalive
                    if await request.is_disconnected():
                        break
                    yield ServerSentEvent(
                        event="heartbeat",
                        data=json.dumps({"ts": datetime.now(UTC).isoformat()}),
                    )
                    continue

                try:
                    parsed: dict[str, object] = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    continue

                event_type: str = str(parsed.get("event", "message"))
                data = parsed.get("data", {})

                yield ServerSentEvent(event=event_type, data=json.dumps(data))

                if event_type in _TERMINAL_EVENTS:
                    break
        finally:
            pump_task.cancel()
            try:
                await pump_task
            except BaseException:
                pass

    return EventSourceResponse(event_generator())
