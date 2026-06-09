"""Redis Pub/Sub broker for distributing real-time session events across workers.

Channel naming convention:
    stream:{tenant_id}:{agent_id}:{session_id}

Each published message is a JSON object:
    {"event": "<event_type>", "data": {…}}

Supported event types:
    message          — a new short-memory message was appended
    memory_extracted — memories were extracted when closing a session
    session_closed   — the session transitioned to closed
    session_archived — the session transitioned to archived
"""

import json
import uuid
from typing import Any


def make_channel(
    tenant_id: uuid.UUID | str,
    agent_id: uuid.UUID | str,
    session_id: uuid.UUID | str,
) -> str:
    """Return the Redis Pub/Sub channel name for a session stream."""
    return f"stream:{tenant_id}:{agent_id}:{session_id}"


async def publish(
    redis: Any,
    channel: str,
    event_type: str,
    data: dict[str, Any],
) -> None:
    """Publish an event to a Redis Pub/Sub channel.

    Uses fire-and-forget semantics — callers should wrap with asyncio.create_task
    when they don't want to block on delivery.
    """
    payload = json.dumps({"event": event_type, "data": data})
    await redis.publish(channel, payload)
