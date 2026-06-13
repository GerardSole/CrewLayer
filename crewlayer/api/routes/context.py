"""Context / blackboard routes.

Route order matters: subscribe endpoints must be registered before the
generic /{namespace}/{key} route, otherwise Starlette would greedily match
/ns/subscribe as key="subscribe".
"""
import asyncio
import base64
import contextlib
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from sse_starlette.sse import EventSourceResponse, ServerSentEvent  # type: ignore[attr-defined]

from crewlayer.api.deps import ContextBrokerDep, DbDep, RedisDep, TenantDep, check_scope
from crewlayer.api.schemas.context import (
    ContextEntryResponse,
    ContextHistoryEntry,
    ContextHistoryResponse,
    ContextNamespaceResponse,
    ContextWrite,
    RollbackRequest,
    RollbackResponse,
)
from crewlayer.core.agents.relations import AgentRelations
from crewlayer.core.context.blackboard import (
    Blackboard,
    RollbackToDeletionError,
    VersionConflictError,
    VersionNotFoundError,
)
from crewlayer.core.streaming.context_broker import (
    make_key_channel,
    make_namespace_pattern,
)
from crewlayer.core.webhooks.dispatcher import dispatch


def _encode_cursor(version: int) -> str:
    return base64.urlsafe_b64encode(str(version).encode()).decode()


def _decode_cursor(cursor: str) -> int:
    return int(base64.urlsafe_b64decode(cursor.encode()).decode())

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
        q = await broker.subscribe(channel, pattern=pattern)
        loop = asyncio.get_running_loop()
        next_heartbeat = loop.time() + _HEARTBEAT_INTERVAL
        try:
            async with asyncio.timeout(_MAX_STREAM_DURATION):
                while True:
                    try:
                        raw = await asyncio.wait_for(q.get(), timeout=_DISCONNECT_CHECK)
                    except TimeoutError:
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

        except TimeoutError:
            yield ServerSentEvent(
                event="timeout",
                data=json.dumps({"reason": "max_duration_reached"}),
            )
        finally:
            with contextlib.suppress(Exception):
                await broker.unsubscribe(channel, q)

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
# History endpoints — registered before /{namespace}/{key} (CRUD)
# ---------------------------------------------------------------------------

@router.get(
    "/{namespace}/{key}/history",
    response_model=ContextHistoryResponse,
    dependencies=[check_scope("context:read")],
    summary="List all changes to a context key (newest first, cursor-paginated)",
)
async def list_history(
    namespace: str,
    key: str,
    tenant: TenantDep,
    db: DbDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
) -> ContextHistoryResponse:
    """Return the immutable change log for *namespace*/*key*, ordered by version descending.

    Use the returned ``next_cursor`` as the ``cursor`` query parameter to fetch
    the next page.  Returns an empty list when all changes have been returned.
    """
    before_version: int | None = None
    if cursor is not None:
        try:
            before_version = _decode_cursor(cursor)
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cursor inválido")

    bb = Blackboard(db)
    entries = await bb.get_history(
        tenant.id, namespace, key,
        before_version=before_version,
        limit=limit + 1,
    )

    next_cursor: str | None = None
    if len(entries) > limit:
        next_cursor = _encode_cursor(entries[limit - 1].version)
        entries = entries[:limit]

    return ContextHistoryResponse(
        namespace=namespace,
        key=key,
        entries=[ContextHistoryEntry.model_validate(e) for e in entries],
        next_cursor=next_cursor,
    )


@router.get(
    "/{namespace}/{key}/history/{version}",
    response_model=ContextHistoryEntry,
    dependencies=[check_scope("context:read")],
    summary="Get the value a key had at a specific version",
)
async def history_at_version(
    namespace: str,
    key: str,
    version: int,
    tenant: TenantDep,
    db: DbDep,
) -> ContextHistoryEntry:
    """Return the exact state of *namespace*/*key* at *version*.

    Returns 404 if that version number does not exist.
    The value is ``null`` when the operation at that version was a deletion.
    """
    bb = Blackboard(db)
    hist = await bb.at_version(tenant.id, namespace, key, version)
    if hist is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Versión no encontrada")
    return ContextHistoryEntry.model_validate(hist)


@router.post(
    "/{namespace}/{key}/rollback",
    response_model=RollbackResponse,
    dependencies=[check_scope("context:write")],
    summary="Restore a context key to an earlier version",
)
async def rollback_entry(
    namespace: str,
    key: str,
    body: RollbackRequest,
    tenant: TenantDep,
    db: DbDep,
    redis: RedisDep,
) -> RollbackResponse:
    """Restore *namespace*/*key* to the value it had at ``target_version``.

    Creates a new history entry with ``operation=rollback``.
    Returns 404 if the target version does not exist.
    Returns 422 if the target version was a deletion (no value to restore).
    """
    bb = Blackboard(db, redis=redis)
    try:
        entry, hist = await bb.rollback(
            tenant.id,
            namespace,
            key,
            body.target_version,
            written_by=body.written_by,
        )
    except VersionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Versión {exc.version} no encontrada",
        )
    except RollbackToDeletionError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"No se puede restaurar la versión {exc.version}: el registro fue eliminado en esa versión",
        )
    await db.commit()
    await db.refresh(entry)
    return RollbackResponse(
        namespace=namespace,
        key=key,
        restored_version=body.target_version,
        new_version=hist.version,
        entry=ContextEntryResponse.model_validate(entry),
    )


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

    if body.propagate and body.written_by is not None:
        ar = AgentRelations(db)
        sub_ids = await ar.get_direct_supervisor_subordinate_ids(tenant.id, body.written_by)
        for sub_id in sub_ids:
            await bb.write(
                tenant_id=tenant.id,
                namespace=str(sub_id),
                key=key,
                value=body.value,
                written_by=body.written_by,
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
