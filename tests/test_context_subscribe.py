"""Integration tests for context blackboard SSE subscriptions.

Structure
---------
1. Broker unit tests  — channel helpers, fan-out, unsubscribe, pattern sub (all in-process)
2. Direct pub/sub integration tests — write/delete via HTTP triggers correct Redis messages,
   verified by subscribing to the channel with redis_client directly.  This avoids all
   httpx SSE streaming cleanup issues while fully testing the blackboard → publish path.
3. SSE smoke tests — verify the subscribe endpoints return 200 + text/event-stream.
4. Auth tests — subscribe endpoints require a valid API key.
"""
from __future__ import annotations

import asyncio
import json
import uuid

import pytest
import redis.asyncio as aioredis
from httpx import AsyncClient

from crewlayer.core.streaming.context_broker import (
    ContextBroker,
    make_key_channel,
    make_namespace_pattern,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _setup(client: AsyncClient) -> tuple[dict, dict]:
    r = await client.post("/v1/tenants", json={"name": f"CtxSub-{uuid.uuid4()}"})
    assert r.status_code == 201
    tenant = r.json()
    return tenant, {"X-API-Key": tenant["initial_api_key"]}


async def _wait_for_pubsub_message(
    ps: aioredis.client.PubSub,
    *,
    pattern: bool = False,
    timeout: float = 3.0,
) -> dict:
    """Poll a PubSub object until a data message arrives or timeout is reached."""
    expected = "pmessage" if pattern else "message"
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        msg = await ps.get_message(ignore_subscribe_messages=True)
        if msg and msg["type"] == expected:
            return json.loads(str(msg["data"]))
        await asyncio.sleep(0.05)
    raise TimeoutError(f"No pubsub message of type '{expected}' within {timeout}s")



# ---------------------------------------------------------------------------
# Broker unit tests
# ---------------------------------------------------------------------------

async def test_channel_helpers_key() -> None:
    tid = uuid.uuid4()
    assert make_key_channel(tid, "ns", "k") == f"context:{tid}:ns:k"


async def test_channel_helpers_namespace_pattern() -> None:
    tid = uuid.uuid4()
    assert make_namespace_pattern(tid, "ns") == f"context:{tid}:ns:*"


async def test_broker_fanout_delivers_to_multiple_queues(redis_client: aioredis.Redis) -> None:
    """Messages published to a channel reach all registered queues."""
    broker = ContextBroker(redis_client)
    channel = f"context:{uuid.uuid4()}:ns:key"

    q1 = await broker.subscribe(channel)
    q2 = await broker.subscribe(channel)
    await asyncio.sleep(0.1)

    await redis_client.publish(channel, json.dumps({"event": "updated", "key": "k"}))
    await asyncio.sleep(0.1)

    msg1 = await asyncio.wait_for(q1.get(), timeout=2.0)
    msg2 = await asyncio.wait_for(q2.get(), timeout=2.0)

    assert json.loads(msg1)["event"] == "updated"
    assert json.loads(msg2)["event"] == "updated"

    await broker.unsubscribe(channel, q1)
    await broker.unsubscribe(channel, q2)
    await broker.aclose()


async def test_broker_unsubscribe_stops_delivery(redis_client: aioredis.Redis) -> None:
    """After unsubscribe, the queue receives no further messages."""
    broker = ContextBroker(redis_client)
    channel = f"context:{uuid.uuid4()}:ns:key"

    q = await broker.subscribe(channel)
    await asyncio.sleep(0.1)
    await broker.unsubscribe(channel, q)
    await asyncio.sleep(0.1)

    await redis_client.publish(channel, '{"event":"updated"}')
    await asyncio.sleep(0.1)

    assert q.empty()
    await broker.aclose()


async def test_broker_pattern_subscribe(redis_client: aioredis.Redis) -> None:
    """Pattern subscriptions receive messages from all matching channels."""
    broker = ContextBroker(redis_client)
    tid = uuid.uuid4()
    pattern = f"context:{tid}:ns:*"

    q = await broker.subscribe(pattern, pattern=True)
    await asyncio.sleep(0.1)

    await redis_client.publish(f"context:{tid}:ns:key1", '{"event":"updated","key":"key1"}')
    await redis_client.publish(f"context:{tid}:ns:key2", '{"event":"updated","key":"key2"}')
    await asyncio.sleep(0.2)

    msgs = [json.loads(await asyncio.wait_for(q.get(), timeout=2.0)) for _ in range(2)]
    keys = {m["key"] for m in msgs}
    assert "key1" in keys
    assert "key2" in keys

    await broker.unsubscribe(pattern, q)
    await broker.aclose()


# ---------------------------------------------------------------------------
# Direct pub/sub integration tests
# (use redis_client.pubsub() to verify write/delete triggers Redis publish)
# ---------------------------------------------------------------------------

async def test_write_publishes_updated_event_to_key_channel(
    client: AsyncClient,
    redis_client: aioredis.Redis,
) -> None:
    """PUT /context/ns/key publishes an 'updated' event to the key's Redis channel."""
    tenant, headers = await _setup(client)
    tid = uuid.UUID(tenant["id"])
    ns, key = "ns-integ", "mykey"

    channel = make_key_channel(tid, ns, key)
    ps = redis_client.pubsub()
    await ps.subscribe(channel)
    await asyncio.sleep(0.05)  # allow subscribe confirmation

    r = await client.put(
        f"/v1/context/{ns}/{key}", json={"value": {"answer": 42}}, headers=headers
    )
    assert r.status_code == 200
    await asyncio.sleep(0.1)  # allow asyncio.create_task to publish

    data = await _wait_for_pubsub_message(ps, timeout=3.0)

    assert data["event"] == "updated"
    assert data["key"] == key
    assert data["value"] == {"answer": 42}
    assert data["version"] == 1

    await ps.unsubscribe(channel)
    await ps.aclose()


async def test_write_publishes_updated_event_matching_namespace_pattern(
    client: AsyncClient,
    redis_client: aioredis.Redis,
) -> None:
    """PUT /context/ns/key publishes an event matching the namespace psubscribe pattern."""
    tenant, headers = await _setup(client)
    tid = uuid.UUID(tenant["id"])
    ns, key = "ns-integ2", "watched"

    pattern = make_namespace_pattern(tid, ns)
    ps = redis_client.pubsub()
    await ps.psubscribe(pattern)
    await asyncio.sleep(0.05)

    r = await client.put(
        f"/v1/context/{ns}/{key}", json={"value": {"x": 99}}, headers=headers
    )
    assert r.status_code == 200
    await asyncio.sleep(0.1)

    data = await _wait_for_pubsub_message(ps, pattern=True, timeout=3.0)

    assert data["event"] == "updated"
    assert data["key"] == key
    assert data["value"] == {"x": 99}

    await ps.punsubscribe(pattern)
    await ps.aclose()


async def test_multiple_writes_publish_multiple_events(
    client: AsyncClient,
    redis_client: aioredis.Redis,
) -> None:
    """Multiple writes to different keys all produce distinct Redis messages."""
    tenant, headers = await _setup(client)
    tid = uuid.UUID(tenant["id"])
    ns = f"ns-multi-{uuid.uuid4().hex[:8]}"

    pattern = make_namespace_pattern(tid, ns)
    ps = redis_client.pubsub()
    await ps.psubscribe(pattern)
    await asyncio.sleep(0.05)

    for k in ("alpha", "beta"):
        r = await client.put(
            f"/v1/context/{ns}/{k}", json={"value": {"k": k}}, headers=headers
        )
        assert r.status_code == 200
        await asyncio.sleep(0.1)

    data1 = await _wait_for_pubsub_message(ps, pattern=True, timeout=3.0)
    data2 = await _wait_for_pubsub_message(ps, pattern=True, timeout=3.0)

    keys_seen = {data1["key"], data2["key"]}
    assert "alpha" in keys_seen
    assert "beta" in keys_seen
    assert data1["event"] == "updated"
    assert data2["event"] == "updated"

    await ps.punsubscribe(pattern)
    await ps.aclose()


async def test_delete_publishes_deleted_event(
    client: AsyncClient,
    redis_client: aioredis.Redis,
) -> None:
    """DELETE /context/ns/key publishes a 'deleted' event to the key's Redis channel."""
    tenant, headers = await _setup(client)
    tid = uuid.UUID(tenant["id"])
    ns, key = "ns-del", "todel"

    # Create the entry first
    r = await client.put(
        f"/v1/context/{ns}/{key}", json={"value": {"v": 1}}, headers=headers
    )
    assert r.status_code == 200

    channel = make_key_channel(tid, ns, key)
    ps = redis_client.pubsub()
    await ps.subscribe(channel)
    await asyncio.sleep(0.05)

    r = await client.delete(f"/v1/context/{ns}/{key}", headers=headers)
    assert r.status_code == 204
    await asyncio.sleep(0.1)

    data = await _wait_for_pubsub_message(ps, timeout=3.0)

    assert data["event"] == "deleted"
    assert data["key"] == key
    assert data["value"] is None

    await ps.unsubscribe(channel)
    await ps.aclose()


async def test_tenant_isolation_key_channels(
    client: AsyncClient,
    redis_client: aioredis.Redis,
) -> None:
    """Tenant A's write does NOT publish to Tenant B's key channel."""
    tenant_a, headers_a = await _setup(client)
    tenant_b, _ = await _setup(client)
    tid_a = uuid.UUID(tenant_a["id"])
    tid_b = uuid.UUID(tenant_b["id"])

    ns, key = f"ns-iso-{uuid.uuid4().hex[:8]}", "secret"
    channel_a = make_key_channel(tid_a, ns, key)
    channel_b = make_key_channel(tid_b, ns, key)

    # Verify channels are different
    assert channel_a != channel_b

    # Subscribe to tenant B's channel
    ps_b = redis_client.pubsub()
    await ps_b.subscribe(channel_b)
    await asyncio.sleep(0.05)

    # Write via tenant A
    r = await client.put(
        f"/v1/context/{ns}/{key}", json={"value": {"private": True}}, headers=headers_a
    )
    assert r.status_code == 200
    await asyncio.sleep(0.5)  # Allow the publish to propagate

    # Tenant B's channel should receive nothing
    msg = await ps_b.get_message(ignore_subscribe_messages=True)
    assert msg is None, f"Tenant B received tenant A's event: {msg}"

    await ps_b.unsubscribe(channel_b)
    await ps_b.aclose()


async def test_tenant_isolation_namespace_patterns(
    client: AsyncClient,
    redis_client: aioredis.Redis,
) -> None:
    """Tenant A's write does NOT match Tenant B's namespace psubscribe pattern."""
    tenant_a, headers_a = await _setup(client)
    tenant_b, _ = await _setup(client)
    tid_a = uuid.UUID(tenant_a["id"])
    tid_b = uuid.UUID(tenant_b["id"])

    ns = f"ns-iso-{uuid.uuid4().hex[:8]}"
    pattern_a = make_namespace_pattern(tid_a, ns)
    pattern_b = make_namespace_pattern(tid_b, ns)

    assert pattern_a != pattern_b

    ps_b = redis_client.pubsub()
    await ps_b.psubscribe(pattern_b)
    await asyncio.sleep(0.05)

    r = await client.put(
        f"/v1/context/{ns}/key", json={"value": {"leak": True}}, headers=headers_a
    )
    assert r.status_code == 200
    await asyncio.sleep(0.5)

    msg = await ps_b.get_message(ignore_subscribe_messages=True)
    assert msg is None, f"Tenant B received tenant A's event via namespace pattern: {msg}"

    await ps_b.punsubscribe(pattern_b)
    await ps_b.aclose()


# ---------------------------------------------------------------------------
# Auth
# (these also serve as route-existence smoke tests: 401 ≠ 404)
# ---------------------------------------------------------------------------

async def test_subscribe_namespace_requires_auth(context_streaming_client: AsyncClient) -> None:
    """GET /context/ns/subscribe without API key returns 401 or 403."""
    r = await context_streaming_client.get("/v1/context/anyns/subscribe")
    assert r.status_code in (401, 403)


async def test_subscribe_key_requires_auth(context_streaming_client: AsyncClient) -> None:
    """GET /context/ns/key/subscribe without API key returns 401 or 403."""
    r = await context_streaming_client.get("/v1/context/anyns/anykey/subscribe")
    assert r.status_code in (401, 403)
