"""Replay engine — replays a recorded action sequence as a live SSE stream."""
import asyncio
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import ServerSentEvent  # type: ignore[attr-defined]

from crewlayer.db.models import Action, Replay, ReplayStatusEnum

_MAX_SLEEP = 60.0  # cap single inter-event delay to avoid stalling streams


async def create_replay(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    from_timestamp: datetime,
    to_timestamp: datetime,
    speed: float = 1.0,
) -> Replay:
    """Create a pending replay job and count actions in the requested window."""
    count: int = await db.scalar(
        select(func.count(Action.id)).where(
            Action.tenant_id == tenant_id,
            Action.agent_id == agent_id,
            Action.timestamp >= from_timestamp,
            Action.timestamp <= to_timestamp,
        )
    ) or 0
    replay = Replay(
        tenant_id=tenant_id,
        agent_id=agent_id,
        from_timestamp=from_timestamp,
        to_timestamp=to_timestamp,
        speed=speed,
        action_count=count,
    )
    db.add(replay)
    await db.flush()
    return replay


async def get_replay(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    replay_id: uuid.UUID,
) -> Replay | None:
    """Retrieve a replay with tenant and agent isolation."""
    result = await db.execute(
        select(Replay).where(
            Replay.id == replay_id,
            Replay.tenant_id == tenant_id,
            Replay.agent_id == agent_id,
        )
    )
    return result.scalar_one_or_none()


async def list_replays(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
) -> list[Replay]:
    """List all replays for an agent ordered newest first."""
    result = await db.execute(
        select(Replay)
        .where(Replay.tenant_id == tenant_id, Replay.agent_id == agent_id)
        .order_by(Replay.created_at.desc())
    )
    return list(result.scalars().all())


def replay_event_stream(
    db: AsyncSession,
    replay: Replay,
    is_disconnected: Callable[[], Awaitable[bool]],
) -> AsyncGenerator[ServerSentEvent, None]:
    """Return an async generator that drives the replay and yields SSE events.

    Status transitions: pending/completed/failed → running → completed (or failed).
    Between consecutive actions the generator sleeps for
    ``delta / speed`` seconds (capped at _MAX_SLEEP), preserving the original
    inter-action cadence at the requested speed multiplier.
    """

    async def _gen() -> AsyncGenerator[ServerSentEvent, None]:
        replay.status = ReplayStatusEnum.running
        replay.started_at = datetime.now(UTC)
        await db.commit()

        try:
            result = await db.execute(
                select(Action)
                .where(
                    Action.tenant_id == replay.tenant_id,
                    Action.agent_id == replay.agent_id,
                    Action.timestamp >= replay.from_timestamp,
                    Action.timestamp <= replay.to_timestamp,
                )
                .order_by(Action.timestamp.asc(), Action.id.asc())
            )
            actions = list(result.scalars().all())
            total = len(actions)

            prev_ts: datetime | None = None
            for i, action in enumerate(actions):
                if await is_disconnected():
                    break

                if prev_ts is not None:
                    delta = (action.timestamp - prev_ts).total_seconds()
                    delay = max(0.0, min(delta / replay.speed, _MAX_SLEEP))
                    if delay > 0:
                        await asyncio.sleep(delay)

                event_data: dict[str, Any] = {
                    "index": i,
                    "total": total,
                    "action_id": str(action.id),
                    "tool_name": action.tool_name,
                    "input_params": action.input_params,
                    "output_result": action.output_result,
                    "status": action.status.value,
                    "duration_ms": action.duration_ms,
                    "error_msg": action.error_msg,
                    "original_timestamp": action.timestamp.isoformat(),
                    "replayed_at": datetime.now(UTC).isoformat(),
                }
                yield ServerSentEvent(event="action", data=json.dumps(event_data))
                prev_ts = action.timestamp

            replay.status = ReplayStatusEnum.completed
            replay.completed_at = datetime.now(UTC)
            await db.commit()

            yield ServerSentEvent(
                event="completed",
                data=json.dumps({
                    "replay_id": str(replay.id),
                    "action_count": total,
                    "completed_at": replay.completed_at.isoformat(),
                }),
            )

        except Exception:
            try:
                replay.status = ReplayStatusEnum.failed
                await db.commit()
            except Exception:
                pass
            raise

    return _gen()
