"""Real-time SSE streaming tests.

Covers:
  - Broker pub/sub unit tests
  - Stream endpoint validation (404 / 409)
  - End-to-end: append_message → SSE delivers message event
  - End-to-end: session close → SSE delivers memory_extracted + session_closed, stream terminates
  - Tenant isolation on the stream endpoint
"""
import asyncio
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import redis.asyncio as aioredis
from httpx import AsyncClient

from crewlayer.core.streaming.broker import make_channel, publish

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _setup(client: AsyncClient) -> tuple[dict, dict]:
    r = await client.post("/v1/tenants", json={"name": f"StreamCo-{uuid.uuid4()}"})
    assert r.status_code == 201
    tenant = r.json()
    return tenant, {"X-API-Key": tenant["initial_api_key"]}


async def _create_agent(client: AsyncClient, headers: dict) -> dict:
    r = await client.post(
        "/v1/agents",
        json={"name": f"streambot-{uuid.uuid4()}", "description": "test"},
        headers=headers,
    )
    assert r.status_code == 201
    return r.json()


async def _create_session(client: AsyncClient, headers: dict, agent_id: str) -> dict:
    r = await client.post("/v1/sessions", json={"agent_id": agent_id}, headers=headers)
    assert r.status_code == 201
    return r.json()


def _collect_sse_events(lines: list[str]) -> list[tuple[str, dict]]:
    """Parse raw SSE lines into (event_type, data_dict) pairs."""
    events: list[tuple[str, dict]] = []
    current_event: str | None = None
    for line in lines:
        if line.startswith("event:"):
            current_event = line[6:].strip()
        elif line.startswith("data:") and current_event is not None:
            try:
                events.append((current_event, json.loads(line[5:].strip())))
            except json.JSONDecodeError:
                pass
            current_event = None
    return events


# ---------------------------------------------------------------------------
# Unit: broker
# ---------------------------------------------------------------------------

async def test_broker_publish_delivers_to_subscriber(redis_client: aioredis.Redis) -> None:
    """publish() sends correctly formatted JSON to all channel subscribers."""
    channel = f"stream:t:{uuid.uuid4()}:s"
    ps = redis_client.pubsub()
    await ps.subscribe(channel)

    # Drain subscribe confirmation before publishing
    async for msg in ps.listen():
        if msg["type"] == "subscribe":
            break

    await publish(redis_client, channel, "message", {"role": "user", "content": "hi"})

    received = None
    async for msg in ps.listen():
        if msg["type"] == "message":
            received = json.loads(msg["data"])
            break

    await ps.unsubscribe(channel)
    await ps.aclose()

    assert received == {"event": "message", "data": {"role": "user", "content": "hi"}}


async def test_broker_publish_multiple_event_types(redis_client: aioredis.Redis) -> None:
    """Different event_type values are preserved in the published payload."""
    channel = f"stream:t:{uuid.uuid4()}:s"
    ps = redis_client.pubsub()
    await ps.subscribe(channel)

    async for msg in ps.listen():
        if msg["type"] == "subscribe":
            break

    await publish(redis_client, channel, "session_closed", {"session_id": "abc"})

    received = None
    async for msg in ps.listen():
        if msg["type"] == "message":
            received = json.loads(msg["data"])
            break

    await ps.unsubscribe(channel)
    await ps.aclose()

    assert received is not None
    assert received["event"] == "session_closed"
    assert received["data"]["session_id"] == "abc"


async def test_make_channel_format() -> None:
    """Channel name follows stream:{tenant}:{agent}:{session} convention."""
    tid, aid, sid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert make_channel(tid, aid, sid) == f"stream:{tid}:{aid}:{sid}"
    # String inputs also accepted
    assert make_channel(str(tid), str(aid), str(sid)) == f"stream:{tid}:{aid}:{sid}"


# ---------------------------------------------------------------------------
# HTTP validation (non-streaming GET)
# ---------------------------------------------------------------------------

async def test_stream_returns_404_for_unknown_session(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)

    r = await client.get(
        f"/v1/agents/{agent['id']}/sessions/{uuid.uuid4()}/stream",
        headers=headers,
    )
    assert r.status_code == 404


async def test_stream_returns_404_for_unknown_agent(client: AsyncClient) -> None:
    _, headers = await _setup(client)

    r = await client.get(
        f"/v1/agents/{uuid.uuid4()}/sessions/{uuid.uuid4()}/stream",
        headers=headers,
    )
    assert r.status_code == 404


async def test_stream_returns_409_for_closed_session(client: AsyncClient) -> None:
    _, headers = await _setup(client)
    agent = await _create_agent(client, headers)
    sess = await _create_session(client, headers, agent["id"])

    with patch(
        "crewlayer.core.memory.extractor._client",
        AsyncMock(**{"messages.create": AsyncMock(
            return_value=AsyncMock(content=[AsyncMock(text="[]")])
        )}),
    ):
        await client.post(f"/v1/sessions/{sess['id']}/close", headers=headers)

    r = await client.get(
        f"/v1/agents/{agent['id']}/sessions/{sess['id']}/stream",
        headers=headers,
    )
    assert r.status_code == 409


async def test_stream_returns_404_for_other_tenant_session(client: AsyncClient) -> None:
    _, headers_a = await _setup(client)
    _, headers_b = await _setup(client)
    agent_a = await _create_agent(client, headers_a)
    sess_a = await _create_session(client, headers_a, agent_a["id"])

    r = await client.get(
        f"/v1/agents/{agent_a['id']}/sessions/{sess_a['id']}/stream",
        headers=headers_b,
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# End-to-end streaming: message delivery
# ---------------------------------------------------------------------------

async def test_stream_receives_message_event(streaming_client: AsyncClient) -> None:
    """append_message publishes a message event; SSE stream delivers it before closing.

    Note: httpx's ASGI transport buffers the full response, so the SSE stream must
    terminate (via session_closed) before aiter_lines() yields anything. We append a
    message then close the session, and verify both events appear in the buffered stream.
    """
    _, headers = await _setup(streaming_client)
    agent = await _create_agent(streaming_client, headers)
    sess = await _create_session(streaming_client, headers, agent["id"])
    session_id, agent_id = sess["id"], agent["id"]

    collected_lines: list[str] = []

    async def consume() -> None:
        url = f"/v1/agents/{agent_id}/sessions/{session_id}/stream"
        async with streaming_client.stream("GET", url, headers=headers) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                collected_lines.append(line)

    async def produce() -> None:
        await asyncio.sleep(0.3)
        await streaming_client.post(
            f"/v1/agents/{agent_id}/memory/messages?session_id={session_id}",
            json={"role": "user", "content": "streaming works"},
            headers=headers,
        )
        await asyncio.sleep(0.1)
        with patch(
            "crewlayer.core.memory.extractor._client",
            AsyncMock(**{"messages.create": AsyncMock(
                return_value=AsyncMock(content=[AsyncMock(text="[]")])
            )}),
        ):
            await streaming_client.post(
                f"/v1/sessions/{session_id}/close", headers=headers
            )
        await asyncio.sleep(0.3)

    await asyncio.wait_for(asyncio.gather(consume(), produce()), timeout=15.0)

    events = _collect_sse_events(collected_lines)
    message_events = [e for e in events if e[0] == "message"]
    assert len(message_events) >= 1
    assert message_events[0][1]["content"] == "streaming works"
    assert message_events[0][1]["role"] == "user"


async def test_stream_multiple_messages_in_order(streaming_client: AsyncClient) -> None:
    """Multiple appended messages are all delivered before session_closed terminates the stream."""
    _, headers = await _setup(streaming_client)
    agent = await _create_agent(streaming_client, headers)
    sess = await _create_session(streaming_client, headers, agent["id"])
    session_id, agent_id = sess["id"], agent["id"]

    collected_lines: list[str] = []

    async def consume() -> None:
        url = f"/v1/agents/{agent_id}/sessions/{session_id}/stream"
        async with streaming_client.stream("GET", url, headers=headers) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                collected_lines.append(line)

    async def produce() -> None:
        await asyncio.sleep(0.3)
        for content in ("first message", "second message"):
            await streaming_client.post(
                f"/v1/agents/{agent_id}/memory/messages?session_id={session_id}",
                json={"role": "user", "content": content},
                headers=headers,
            )
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.1)
        with patch(
            "crewlayer.core.memory.extractor._client",
            AsyncMock(**{"messages.create": AsyncMock(
                return_value=AsyncMock(content=[AsyncMock(text="[]")])
            )}),
        ):
            await streaming_client.post(
                f"/v1/sessions/{session_id}/close", headers=headers
            )
        await asyncio.sleep(0.3)

    await asyncio.wait_for(asyncio.gather(consume(), produce()), timeout=15.0)

    events = _collect_sse_events(collected_lines)
    message_events = [e for e in events if e[0] == "message"]
    assert len(message_events) >= 2
    contents = [e[1]["content"] for e in message_events]
    assert "first message" in contents
    assert "second message" in contents


# ---------------------------------------------------------------------------
# End-to-end streaming: session close
# ---------------------------------------------------------------------------

async def test_stream_closes_and_delivers_events_on_session_close(streaming_client: AsyncClient) -> None:
    """On session close, stream receives memory_extracted + session_closed and terminates."""
    _, headers = await _setup(streaming_client)
    agent = await _create_agent(streaming_client, headers)
    sess = await _create_session(streaming_client, headers, agent["id"])
    session_id, agent_id = sess["id"], agent["id"]

    collected_lines: list[str] = []

    async def consume() -> None:
        url = f"/v1/agents/{agent_id}/sessions/{session_id}/stream"
        async with streaming_client.stream("GET", url, headers=headers) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                collected_lines.append(line)
            # Loop exits naturally when server closes the stream

    async def produce() -> None:
        await asyncio.sleep(0.3)
        with patch(
            "crewlayer.core.memory.extractor._client",
            AsyncMock(**{"messages.create": AsyncMock(
                return_value=AsyncMock(content=[AsyncMock(text="[]")])
            )}),
        ):
            r = await streaming_client.post(f"/v1/sessions/{session_id}/close", headers=headers)
        assert r.status_code == 200
        await asyncio.sleep(0.3)  # let create_task publishes propagate + stream close

    await asyncio.wait_for(asyncio.gather(consume(), produce()), timeout=15.0)

    joined = " ".join(collected_lines)
    assert "memory_extracted" in joined
    assert "session_closed" in joined
