"""Fan-out broker for blackboard change events via Redis Pub/Sub.

One Redis Pub/Sub connection is maintained per active channel; messages are
distributed to all in-process asyncio Queues registered for that channel.
This avoids creating one Redis connection per SSE subscriber.

Channel naming
--------------
Key-level:       context:{tenant_id}:{namespace}:{key}
Namespace-level: context:{tenant_id}:{namespace}:*   (psubscribe pattern)

The broker is stored in app.state (initialised in main.py lifespan) and
accessed from routes via the ContextBrokerDep dependency.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections import defaultdict

import redis.asyncio as aioredis

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Channel helpers
# ---------------------------------------------------------------------------

def make_key_channel(tenant_id: uuid.UUID, namespace: str, key: str) -> str:
    """Exact-match channel for a single context key."""
    return f"context:{tenant_id}:{namespace}:{key}"


def make_namespace_pattern(tenant_id: uuid.UUID, namespace: str) -> str:
    """psubscribe pattern that matches every key in a namespace."""
    return f"context:{tenant_id}:{namespace}:*"


# ---------------------------------------------------------------------------
# Broker
# ---------------------------------------------------------------------------

class ContextBroker:
    """Shared fan-out broker.

    Lifecycle:
    * ``subscribe()``   — register a consumer Queue; start a pump if needed.
    * ``unsubscribe()`` — remove the Queue; cancel the pump when the channel
                          has no more consumers.
    * ``aclose()``      — tear down all pumps (called from lifespan on shutdown).
    """

    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis
        # channel → set of consumer queues
        self._queues: dict[str, set[asyncio.Queue[str]]] = defaultdict(set)
        # channel → running pump task
        self._pumps: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(
        self,
        channel: str,
        *,
        pattern: bool = False,
    ) -> asyncio.Queue[str]:
        """Return a new Queue that will receive messages from *channel*.

        Starts a pump task for the channel if none is running yet.
        """
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=512)
        async with self._lock:
            self._queues[channel].add(q)
            if channel not in self._pumps:
                self._pumps[channel] = asyncio.create_task(
                    self._pump(channel, pattern=pattern),
                    name=f"ctx_pump:{channel[:80]}",
                )
        return q

    async def unsubscribe(self, channel: str, q: asyncio.Queue[str]) -> None:
        """Remove *q* from *channel*; cancel the pump when the channel is empty."""
        async with self._lock:
            queues = self._queues.get(channel)
            if queues is not None:
                queues.discard(q)
                if not queues:
                    self._queues.pop(channel, None)
                    task = self._pumps.pop(channel, None)
                    if task and not task.done():
                        task.cancel()

    async def _pump(self, channel: str, *, pattern: bool) -> None:
        """Redis listener that fans messages out to all registered queues."""
        ps = self._redis.pubsub()
        if pattern:
            await ps.psubscribe(channel)
        else:
            await ps.subscribe(channel)
        try:
            async for msg in ps.listen():
                if msg.get("type") not in ("message", "pmessage"):
                    continue
                payload = str(msg["data"])
                # Take a snapshot of current queues under the lock, then
                # deliver without holding the lock to avoid blocking subscribe/unsubscribe.
                async with self._lock:
                    targets = set(self._queues.get(channel, set()))
                for target_q in targets:
                    with contextlib.suppress(asyncio.QueueFull):
                        target_q.put_nowait(payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log.warning("context_broker pump error on %s: %s", channel, exc)
        finally:
            with contextlib.suppress(Exception):
                if pattern:
                    await ps.punsubscribe(channel)
                else:
                    await ps.unsubscribe(channel)
            with contextlib.suppress(Exception):
                await ps.aclose()  # type: ignore[no-untyped-call]

    async def aclose(self) -> None:
        """Cancel all active pumps."""
        async with self._lock:
            for task in list(self._pumps.values()):
                if not task.done():
                    task.cancel()
            self._pumps.clear()
            self._queues.clear()
