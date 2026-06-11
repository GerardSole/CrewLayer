import base64
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from opentelemetry import trace
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.db.models import Action, ActionStatus

_tracer = trace.get_tracer("crewlayer.actions")

# ---------------------------------------------------------------------------
# Cursor helpers — keyset pagination on (timestamp DESC, id DESC)
# ---------------------------------------------------------------------------

def _encode_cursor(timestamp: datetime, action_id: uuid.UUID) -> str:
    raw = f"{timestamp.isoformat()}|{action_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID] | None:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts_str, id_str = raw.split("|", 1)
        return datetime.fromisoformat(ts_str), uuid.UUID(id_str)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Filter + stats dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ActionFilters:
    tool_name: str | None = None
    status: ActionStatus | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = 50
    cursor: str | None = None


@dataclass
class ToolStat:
    tool_name: str
    count: int
    avg_duration_ms: float | None
    error_rate: float


@dataclass
class ActionStats:
    total_actions: int
    error_rate: float
    avg_duration_ms: float | None
    by_tool: list[ToolStat] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

class ActionLogger:
    """Append-only store for agent action records."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def log(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        tool_name: str,
        input_params: dict[str, Any],
        output_result: dict[str, Any],
        status: ActionStatus,
        *,
        session_id: uuid.UUID | None = None,
        duration_ms: int | None = None,
        error_msg: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Action:
        """Insert an immutable action record and flush (caller must commit)."""
        with _tracer.start_as_current_span("actions.log") as span:
            span.set_attribute("tenant_id", str(tenant_id))
            span.set_attribute("agent_id", str(agent_id))
            span.set_attribute("tool_name", tool_name)
            span.set_attribute("status", status.value)
            if duration_ms is not None:
                span.set_attribute("duration_ms", duration_ms)

            action = Action(
                tenant_id=tenant_id,
                agent_id=agent_id,
                session_id=session_id,
                tool_name=tool_name,
                input_params=input_params,
                output_result=output_result,
                status=status,
                duration_ms=duration_ms,
                error_msg=error_msg,
                metadata_=metadata or {},
            )
            self._db.add(action)
            await self._db.flush()
            return action

    async def get(self, tenant_id: uuid.UUID, action_id: uuid.UUID) -> Action | None:
        """Fetch one action, enforcing tenant ownership."""
        result = await self._db.execute(
            select(Action).where(
                Action.id == action_id,
                Action.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        filters: ActionFilters,
    ) -> tuple[list[Action], str | None]:
        """Return (actions, next_cursor).

        Sorted by (timestamp DESC, id DESC). next_cursor is None when
        the page is the last one.
        """
        conditions: list[Any] = [
            Action.tenant_id == tenant_id,
            Action.agent_id == agent_id,
        ]

        if filters.tool_name:
            conditions.append(Action.tool_name == filters.tool_name)
        if filters.status:
            conditions.append(Action.status == filters.status)
        if filters.since:
            conditions.append(Action.timestamp >= filters.since)
        if filters.until:
            conditions.append(Action.timestamp <= filters.until)

        if filters.cursor:
            decoded = _decode_cursor(filters.cursor)
            if decoded:
                cursor_ts, cursor_id = decoded
                # Keyset: rows that come *after* cursor in DESC order
                conditions.append(
                    or_(
                        Action.timestamp < cursor_ts,
                        and_(Action.timestamp == cursor_ts, Action.id < cursor_id),
                    )
                )

        stmt = (
            select(Action)
            .where(*conditions)
            .order_by(Action.timestamp.desc(), Action.id.desc())
            .limit(filters.limit + 1)  # +1 to detect whether a next page exists
        )
        rows = list((await self._db.execute(stmt)).scalars().all())

        has_more = len(rows) > filters.limit
        page = rows[: filters.limit]

        next_cursor: str | None = None
        if has_more and page:
            last = page[-1]
            next_cursor = _encode_cursor(last.timestamp, last.id)

        return page, next_cursor

    async def stats(self, tenant_id: uuid.UUID, agent_id: uuid.UUID) -> ActionStats:
        """Return aggregate stats for all actions by this agent."""
        base_where = [Action.tenant_id == tenant_id, Action.agent_id == agent_id]

        # Overall totals
        overall = (
            await self._db.execute(
                select(
                    func.count().label("total"),
                    func.avg(Action.duration_ms).label("avg_duration"),
                    func.sum(
                        case((Action.status == ActionStatus.error, 1), else_=0)
                    ).label("errors"),
                ).where(*base_where)
            )
        ).one()

        total: int = overall.total or 0
        avg_ms = float(overall.avg_duration) if overall.avg_duration is not None else None
        errors: int = int(overall.errors or 0)
        error_rate = errors / total if total > 0 else 0.0

        # Per-tool breakdown
        tool_rows = (
            await self._db.execute(
                select(
                    Action.tool_name,
                    func.count().label("action_count"),
                    func.avg(Action.duration_ms).label("avg_duration"),
                    func.sum(
                        case((Action.status == ActionStatus.error, 1), else_=0)
                    ).label("errors"),
                )
                .where(*base_where)
                .group_by(Action.tool_name)
                .order_by(func.count().desc())
            )
        ).all()

        by_tool = [
            ToolStat(
                tool_name=r.tool_name,
                count=r.action_count,
                avg_duration_ms=float(r.avg_duration) if r.avg_duration is not None else None,
                error_rate=int(r.errors or 0) / r.action_count if r.action_count > 0 else 0.0,
            )
            for r in tool_rows
        ]

        return ActionStats(
            total_actions=total,
            error_rate=error_rate,
            avg_duration_ms=avg_ms,
            by_tool=by_tool,
        )
