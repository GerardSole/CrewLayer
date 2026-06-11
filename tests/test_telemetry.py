"""Unit tests for OpenTelemetry custom spans.

These tests use the OTel in-memory exporter — no real DB or Redis required.
Each test verifies that the correct span name and attributes are emitted.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


@pytest.fixture(scope="session")
def _otel_exporter() -> InMemorySpanExporter:
    """Install a real TracerProvider once per session; return the in-memory exporter."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    # set_tracer_provider may only succeed once per process — that's fine here.
    trace.set_tracer_provider(provider)
    return exporter


@pytest.fixture
def otel(_otel_exporter: InMemorySpanExporter) -> InMemorySpanExporter:  # type: ignore[misc]
    """Clear the exporter before each test and yield it for assertions."""
    _otel_exporter.clear()
    yield _otel_exporter  # type: ignore[misc]


def _span(exporter: InMemorySpanExporter, name: str):  # type: ignore[return]
    """Return the first finished span with *name*, or fail with a helpful message."""
    spans = exporter.get_finished_spans()
    found = [s for s in spans if s.name == name]
    assert found, f"No span named {name!r}. Got: {[s.name for s in spans]}"
    return found[0]


# ---------------------------------------------------------------------------
# memory.recall
# ---------------------------------------------------------------------------


async def test_memory_recall_span_attributes(otel: InMemorySpanExporter) -> None:
    from crewlayer.core.memory.long import LongMemory

    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()

    mock_db = AsyncMock()
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None  # cache miss

    mock_exec = MagicMock()
    mock_exec.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_exec)

    with patch("crewlayer.core.memory.long.get_embedding", AsyncMock(return_value=[0.1] * 1536)):
        lm = LongMemory(mock_db, mock_redis)
        await lm.recall(tenant_id, agent_id, "what does the user prefer", limit=5)

    s = _span(otel, "memory.recall")
    assert s.attributes["query"] == "what does the user prefer"
    assert s.attributes["top_k"] == 5
    assert s.attributes["results_count"] == 0
    assert s.attributes["embedding_cache_hit"] is False


async def test_memory_recall_cache_hit(otel: InMemorySpanExporter) -> None:
    from crewlayer.core.memory.long import LongMemory

    mock_db = AsyncMock()
    mock_redis = AsyncMock()
    mock_redis.get.return_value = b"[0.1]"  # non-None → cache hit

    mock_exec = MagicMock()
    mock_exec.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_exec)

    with patch("crewlayer.core.memory.long.get_embedding", AsyncMock(return_value=[0.1] * 1536)):
        lm = LongMemory(mock_db, mock_redis)
        await lm.recall(uuid.uuid4(), uuid.uuid4(), "cached query", limit=3)

    s = _span(otel, "memory.recall")
    assert s.attributes["embedding_cache_hit"] is True


# ---------------------------------------------------------------------------
# memory.deduplicate
# ---------------------------------------------------------------------------


async def test_memory_deduplicate_no_duplicate(otel: InMemorySpanExporter) -> None:
    from crewlayer.core.memory.long import LongMemory

    mock_db = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.add = MagicMock()

    with (
        patch("crewlayer.core.memory.long.get_embedding", AsyncMock(return_value=[0.1] * 1536)),
        patch("crewlayer.core.memory.long.find_near_duplicate", AsyncMock(return_value=None)),
    ):
        lm = LongMemory(mock_db)
        await lm.save(uuid.uuid4(), uuid.uuid4(), "brand new memory")

    s = _span(otel, "memory.deduplicate")
    assert s.attributes["duplicates_found"] == 0
    assert s.attributes["merges_performed"] == 0


async def test_memory_deduplicate_with_merge(otel: InMemorySpanExporter) -> None:
    from crewlayer.core.memory.long import LongMemory

    mock_db = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.add = MagicMock()

    existing = MagicMock()
    existing.content = "existing fact"
    existing.base_importance = 0.7
    existing.tags = ["ai"]
    existing.access_count = 1
    existing.last_accessed = None
    existing.id = uuid.uuid4()

    with (
        patch("crewlayer.core.memory.long.get_embedding", AsyncMock(return_value=[0.1] * 1536)),
        patch("crewlayer.core.memory.long.find_near_duplicate", AsyncMock(return_value=existing)),
        patch("crewlayer.core.memory.long.call_claude_merge", AsyncMock(return_value="merged fact")),
    ):
        lm = LongMemory(mock_db)
        await lm.save(uuid.uuid4(), uuid.uuid4(), "similar fact")

    s = _span(otel, "memory.deduplicate")
    assert s.attributes["duplicates_found"] == 1
    assert s.attributes["merges_performed"] == 1


# ---------------------------------------------------------------------------
# memory.extract
# ---------------------------------------------------------------------------


async def test_memory_extract_span(otel: InMemorySpanExporter) -> None:
    from crewlayer.core.memory.extractor import extract_and_save

    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    session_id = str(uuid.uuid4())

    saved_mem = MagicMock()
    saved_mem.id = uuid.uuid4()

    mock_lm = AsyncMock()
    mock_lm.save = AsyncMock(return_value=saved_mem)

    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(text='[{"content": "user prefers dark mode", "importance": 0.8, "tags": ["ui"]}]')
    ]

    with patch("crewlayer.core.memory.extractor._client") as mock_client:
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        await extract_and_save(tenant_id, agent_id, "conversation text", mock_lm, session_id=session_id)

    s = _span(otel, "memory.extract")
    assert s.attributes["session_id"] == session_id
    assert s.attributes["memories_extracted"] == 1
    assert s.attributes["model_used"] == "claude-opus-4-8"


async def test_memory_extract_span_no_session(otel: InMemorySpanExporter) -> None:
    from crewlayer.core.memory.extractor import extract_and_save

    saved_mem = MagicMock()
    saved_mem.id = uuid.uuid4()
    mock_lm = AsyncMock()
    mock_lm.save = AsyncMock(return_value=saved_mem)

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='[{"content": "fact", "importance": 0.5, "tags": []}]')]

    with patch("crewlayer.core.memory.extractor._client") as mock_client:
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        await extract_and_save(uuid.uuid4(), uuid.uuid4(), "text", mock_lm)

    s = _span(otel, "memory.extract")
    assert "session_id" not in s.attributes
    assert s.attributes["memories_extracted"] == 1


# ---------------------------------------------------------------------------
# actions.log
# ---------------------------------------------------------------------------


async def test_actions_log_span(otel: InMemorySpanExporter) -> None:
    from crewlayer.core.actions.logger import ActionLogger
    from crewlayer.db.models import ActionStatus

    mock_db = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.add = MagicMock()

    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()

    logger = ActionLogger(mock_db)
    await logger.log(
        tenant_id,
        agent_id,
        "web_search",
        {"query": "python"},
        {"result": "found"},
        ActionStatus.success,
        duration_ms=312,
    )

    s = _span(otel, "actions.log")
    assert s.attributes["tool_name"] == "web_search"
    assert s.attributes["status"] == "success"
    assert s.attributes["duration_ms"] == 312


async def test_actions_log_span_no_duration(otel: InMemorySpanExporter) -> None:
    from crewlayer.core.actions.logger import ActionLogger
    from crewlayer.db.models import ActionStatus

    mock_db = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.add = MagicMock()

    await ActionLogger(mock_db).log(
        uuid.uuid4(), uuid.uuid4(), "tool", {}, {}, ActionStatus.error
    )

    s = _span(otel, "actions.log")
    assert s.attributes["status"] == "error"
    assert "duration_ms" not in s.attributes


# ---------------------------------------------------------------------------
# context.write
# ---------------------------------------------------------------------------


async def test_context_write_span(otel: InMemorySpanExporter) -> None:
    from crewlayer.core.context.blackboard import Blackboard

    tenant_id = uuid.uuid4()
    mock_db = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.add = MagicMock()

    # First execute: SELECT ContextEntry → None (new key)
    mock_no_entry = MagicMock()
    mock_no_entry.scalar_one_or_none.return_value = None
    # Second execute: SELECT max(version) → 0
    mock_max_v = MagicMock()
    mock_max_v.scalar_one.return_value = 0

    mock_db.execute = AsyncMock(side_effect=[mock_no_entry, mock_max_v])

    bb = Blackboard(mock_db)
    await bb.write(tenant_id, "shared", "config", {"theme": "dark"})

    s = _span(otel, "context.write")
    assert s.attributes["namespace"] == "shared"
    assert s.attributes["key"] == "config"
    assert s.attributes["version"] == 1


# ---------------------------------------------------------------------------
# webhooks.dispatch
# ---------------------------------------------------------------------------


async def test_webhooks_dispatch_span_no_endpoints(otel: InMemorySpanExporter) -> None:
    import crewlayer.core.webhooks.dispatcher as dispatcher_mod

    tenant_id = uuid.uuid4()
    event = "memory.created"

    mock_db = AsyncMock()
    mock_exec = MagicMock()
    mock_exec.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_exec)

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch.object(dispatcher_mod, "_session_factory", return_value=mock_cm):
        tasks = await dispatcher_mod.dispatch(tenant_id, event, {"data": 1})

    assert tasks == []
    s = _span(otel, "webhooks.dispatch")
    assert s.attributes["event"] == event
    assert s.attributes["endpoints_count"] == 0
    assert s.attributes["success_count"] == 0
