import uuid
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.core.webhooks.dispatcher import dispatch
from crewlayer.db.models import Action, ActionStatus

_RATE_WINDOW = 20


def _parse_config(config: dict[str, Any]) -> tuple[bool, int, int]:
    """Return (alerts_enabled, consec_threshold, rate_threshold_percent)."""
    return (
        bool(config.get("alerts_enabled", True)),
        int(config.get("alert_on_consecutive_errors", 5)),
        int(config.get("alert_on_error_rate_percent", 80)),
    )


async def check_and_fire_alerts(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    agent_name: str,
    agent_config: dict[str, Any],
    action_status: ActionStatus,
    action_id: uuid.UUID,
    db: AsyncSession,
    redis: Redis,
) -> None:
    """After an action is committed, update Redis counters and fire agent.alert if thresholds exceeded."""
    alerts_enabled, consec_threshold, rate_threshold = _parse_config(agent_config)
    if not alerts_enabled:
        return

    is_error = action_status in (ActionStatus.error, ActionStatus.timeout)
    redis_key = f"alert:{tenant_id}:{agent_id}:consecutive_errors"

    if is_error:
        count = int(await redis.incr(redis_key))
    else:
        await redis.set(redis_key, 0)
        return  # success resets the counter; no alert needed

    timestamp = datetime.now(UTC).isoformat()
    base_payload: dict[str, Any] = {
        "agent_id": str(agent_id),
        "agent_name": agent_name,
        "last_action_id": str(action_id),
        "timestamp": timestamp,
    }

    # Consecutive-errors alert takes priority
    if count >= consec_threshold:
        await dispatch(tenant_id, "agent.alert", {
            **base_payload,
            "alert_type": "consecutive_errors",
            "threshold": consec_threshold,
            "current_value": count,
        })
        await redis.set(redis_key, 0)
        return

    # Error-rate alert — only meaningful once the window is full
    errors, total = await _recent_error_rate(tenant_id, agent_id, _RATE_WINDOW, db)
    if total >= _RATE_WINDOW:
        rate_percent = errors * 100 // total
        if rate_percent >= rate_threshold:
            await dispatch(tenant_id, "agent.alert", {
                **base_payload,
                "alert_type": "error_rate",
                "threshold": rate_threshold,
                "current_value": rate_percent,
            })


async def _recent_error_rate(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    window: int,
    db: AsyncSession,
) -> tuple[int, int]:
    """Return (error_count, total_count) for the last `window` actions."""
    subq = (
        select(Action.status)
        .where(Action.tenant_id == tenant_id, Action.agent_id == agent_id)
        .order_by(Action.timestamp.desc())
        .limit(window)
        .subquery()
    )
    row = (
        await db.execute(
            select(
                func.count().label("total"),
                func.sum(
                    case(
                        (subq.c.status.in_(["error", "timeout"]), 1),
                        else_=0,
                    )
                ).label("errors"),
            ).select_from(subq)
        )
    ).one()
    return int(row.errors or 0), int(row.total or 0)
