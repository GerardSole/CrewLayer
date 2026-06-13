"""Audit log query endpoint.

GET /v1/audit-log — list immutable audit events for the authenticated tenant.

Filters: resource_type, from (ISO datetime), to (ISO datetime).
Pagination: cursor-based (newest first).  No DELETE endpoint is exposed.
"""

import base64
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from crewlayer.api.deps import DbDep, TenantDep
from crewlayer.api.schemas.audit import AuditLogEntry, AuditLogListResponse
from crewlayer.db.models import AuditLog

router = APIRouter()


def _encode_cursor(ts: datetime, eid: uuid.UUID) -> str:
    raw = f"{ts.isoformat()}|{eid}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID] | None:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts_str, id_str = raw.split("|", 1)
        return datetime.fromisoformat(ts_str), uuid.UUID(id_str)
    except Exception:
        return None


@router.get("/audit-log", response_model=AuditLogListResponse)
async def list_audit_log(
    tenant: TenantDep,
    db: DbDep,
    resource_type: Annotated[str | None, Query()] = None,
    from_ts: Annotated[datetime | None, Query(alias="from")] = None,
    to_ts: Annotated[datetime | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    cursor: Annotated[str | None, Query()] = None,
) -> AuditLogListResponse:
    """List audit log entries for the authenticated tenant, newest first.

    Supports filtering by resource_type and time range.  Use the returned
    next_cursor to fetch subsequent pages.
    """
    stmt = select(AuditLog).where(AuditLog.tenant_id == tenant.id)

    if resource_type is not None:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    if from_ts is not None:
        stmt = stmt.where(AuditLog.timestamp >= from_ts)
    if to_ts is not None:
        stmt = stmt.where(AuditLog.timestamp <= to_ts)

    if cursor is not None:
        decoded = _decode_cursor(cursor)
        if decoded is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cursor inválido",
            )
        cursor_ts, cursor_id = decoded
        # Next page: items strictly older than cursor position (newest-first order)
        stmt = stmt.where(
            (AuditLog.timestamp < cursor_ts)
            | ((AuditLog.timestamp == cursor_ts) & (AuditLog.id < cursor_id))
        )

    stmt = stmt.order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).limit(limit)

    rows = (await db.execute(stmt)).scalars().all()

    next_cursor: str | None = None
    if len(rows) == limit:
        last = rows[-1]
        next_cursor = _encode_cursor(last.timestamp, last.id)

    return AuditLogListResponse(
        items=[AuditLogEntry.model_validate(r) for r in rows],
        next_cursor=next_cursor,
    )
