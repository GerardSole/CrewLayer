"""Context / blackboard routes.

Route order matters: subscribe endpoints must be registered before the
generic /{namespace}/{key} route, otherwise Starlette would greedily match
/ns/subscribe as key="subscribe".
"""
import asyncio
import contextlib
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sse_starlette.sse import EventSourceResponse, ServerSentEvent  # type: ignore[attr-defined]

from crewlayer.api.deps import ContextBrokerDep, DbDep, RedisDep, TenantDep, check_scope
from crewlayer.api.schemas.context import (
    ContextEntryResponse,
    ContextNamespaceResponse,
    ContextWrite,
)
from crewlayer.core.context.blackboard import Blackboard, VersionConflictError
from crewlayer.core.streaming.context_broker import (
    make_key_channel,
    make_namespace_pattern,
)
from crewlayer.core.webhooks.dispatcher import dispatch

router = APIRouter()

_DISCONNECT_CHECK = 1.0      # poll interval for client disconnect detection
_HEARTBEAT_INTERVAL = 30.0   # seconds between SSE heartbeats
_MAX_STREAM_DURATION = 3600.0  # 1 hour; close the stream regardless of activity


# ---------------------------------------------------------------------------
# SSE subscribe helpers
# ---------------------------------------------------------------------------

def _sse_generator(
    request: Request,
    channel: str,
    broker: "ContextBrokerDep",  # type annotation only; actual type is ContextBroker
    *,
    pattern: bool,
) -> AsyncGenerator[ServerSentEvent, None]:
    """Return an async generator that emits SSE events from *channel*.

    Uses a 1-second poll interval so client disconnects are detected quickly
    (important for clean resource release in tests and production alike).
    Heartbeats are emitted every 30 s independent of the poll interval.
    """

    async def _gen() -> AsyncGenerator[ServerSentEvent, None]:
        q = await broker.subscribe(channel, pattern=pattern)  # type: ignore[attr-defined]
        loop = asyncio.get_running_loop()
        next_heartbeat = loop.time() + _HEARTBEAT_INTERVAL
        try:
            async with asyncio.timeout(_MAX_STREAM_DURATION):
                while True:
                    try:
                        raw = await asyncio.wait_for(q.get(), timeout=_DISCONNECT_CHECK)
                    except asyncio.TimeoutError:
                        if await request.is_disconnected():
                            break
                        now = loop.time()
                        if now >= next_heartbeat:
                            yield ServerSentEvent(
                                event="heartbeat",
                                data=json.dumps({"ts": datetime.now(UTC).isoformat()}),
                            )
                            next_heartbeat = now + _HEARTBEAT_INTERVAL
                        continue

                    try:
                        parsed: dict[str, object] = json.loads(raw)
                    except (json.JSONDecodeError, ValueError):
                        continue

                    event_type = str(parsed.get("event", "updated"))
                    yield ServerSentEvent(event=event_type, data=raw)

        except (asyncio.TimeoutError, TimeoutError):
            yield ServerSentEvent(
                event="timeout",
                data=json.dumps({"reason": "max_duration_reached"}),
            )
        finally:
            with contextlib.suppress(Exception):
                await broker.unsubscribe(channel, q)  # type: ignore[attr-defined]

    return _gen()


# ---------------------------------------------------------------------------
# Subscribe endpoints — must be registered BEFORE /{namespace}/{key}
# ---------------------------------------------------------------------------

@router.get(
    "/{namespace}/subscribe",
    dependencies=[check_scope("context:read")],
    summary="Subscribe to all changes in a namespace via SSE",
)
async def subscribe_namespace(
    namespace: str,
    request: Request,
    tenant: TenantDep,
    broker: ContextBrokerDep,
) -> EventSourceResponse:
    """Open an SSE stream that emits every change (write or delete) within *namespace*.

    Events:
      ``updated``   — a key was written (payload includes key, value, version).
      ``deleted``   — a key was deleted.
      ``heartbeat`` — keepalive every 30 s.
      ``timeout``   — connection closed after 1 h of total duration.
    """
    channel = make_namespace_pattern(tenant.id, namespace)
    return EventSourceResponse(_sse_generator(request, channel, broker, pattern=True))


@router.get(
    "/{namespace}/{key}/subscribe",
    dependencies=[check_scope("context:read")],
    summary="Subscribe to changes on a single context key via SSE",
)
async def subscribe_key(
    namespace: str,
    key: str,
    request: Request,
    tenant: TenantDep,
    broker: ContextBrokerDep,
) -> EventSourceResponse:
    """Open an SSE stream that emits changes to a specific *namespace*/*key*.

    Events are the same as the namespace-level subscription but filtered
    to the single key.
    """
    channel = make_key_channel(tenant.id, namespace, key)
    return EventSourceResponse(_sse_generator(request, channel, broker, pattern=False))


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------

@router.put(
    "/{namespace}/{key}",
    response_model=ContextEntryResponse,
    dependencies=[check_scope("context:write")],
)
async def write_entry(
    namespace: str,
    key: str,
    body: ContextWrite,
    tenant: TenantDep,
    db: DbDep,
    redis: RedisDep,
) -> ContextEntryResponse:
    """Write or overwrite a context entry. Optionally enforce optimistic locking
    by providing expected_version (use 0 to assert the key must not yet exist)."""
    bb = Blackboard(db, redis=redis)
    try:
        entry = await bb.write(
            tenant_id=tenant.id,
            namespace=namespace,
            key=key,
            value=body.value,
            written_by=body.written_by,
            expires_at=body.expires_at,
            expected_version=body.expected_version,
        )
    except VersionConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Version conflict: expected {exc.expected}, current is {exc.actual}",
        )
    await db.commit()
    await db.refresh(entry)
    asyncio.create_task(
        dispatch(
            tenant.id,
            "context.updated",
            {"namespace": namespace, "key": key, "version": entry.version},
        )
    )
    return ContextEntryResponse.model_validate(entry)


@router.get(
    "/{namespace}/{key}",
    response_model=ContextEntryResponse,
    dependencies=[check_scope("context:read")],
)
async def read_entry(
    namespace: str,
    key: str,
    tenant: TenantDep,
    db: DbDep,
) -> ContextEntryResponse:
    """Read a context entry. Returns 404 if absent or expired."""
    bb = Blackboard(db)
    entry = await bb.read(tenant.id, namespace, key)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entrada no encontrada")
    return ContextEntryResponse.model_validate(entry)


@router.get(
    "/{namespace}",
    response_model=ContextNamespaceResponse,
    dependencies=[check_scope("context:read")],
)
async def list_namespace(
    namespace: str,
    tenant: TenantDep,
    db: DbDep,
) -> ContextNamespaceResponse:
    """List all non-expired entries in a namespace, ordered by key."""
    bb = Blackboard(db)
    entries = await bb.list_namespace(tenant.id, namespace)
    return ContextNamespaceResponse(
        namespace=namespace,
        entries=[ContextEntryResponse.model_validate(e) for e in entries],
        count=len(entries),
    )


@router.delete(
    "/{namespace}/{key}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[check_scope("context:write")],
)
async def delete_entry(
    namespace: str,
    key: str,
    tenant: TenantDep,
    db: DbDep,
    redis: RedisDep,
) -> None:
    """Delete a context entry."""
    bb = Blackboard(db, redis=redis)
    deleted = await bb.delete(tenant.id, namespace, key)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entrada no encontrada")
    await db.commit()
