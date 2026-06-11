"""Tests for sdk/crewlayer/integrations/llamaindex.py.

All tests use mock clients — no real LlamaIndex or CrewLayer server required.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from crewlayer.integrations.llamaindex import (
    CrewLayerCallbackManager,
    CrewLayerMemoryBuffer,
    CrewLayerQueryEngine,
    CrewLayerVectorIndex,
    QueryResponse,
    _event_name,
    _role_str,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(messages=None, recall_results=None, extract_ids=None) -> MagicMock:
    client = MagicMock()
    client.memory.messages.return_value = SimpleNamespace(
        messages=messages or [], session_id="default", count=len(messages or [])
    )
    client.memory.recall.return_value = SimpleNamespace(results=recall_results or [])
    client.memory.extract.return_value = SimpleNamespace(
        memory_ids=extract_ids or ["mem-1"], extracted_count=len(extract_ids or ["mem-1"])
    )
    return client


def _msg(role: str, content: str) -> SimpleNamespace:
    return SimpleNamespace(role=role, content=content)


def _memory_item(
    content: str,
    similarity: float = 0.88,
    importance: float = 0.7,
    tags: list | None = None,
    id: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id or str(uuid.uuid4()),
        content=content,
        similarity=similarity,
        importance=importance,
        tags=tags or [],
    )


def _chat_msg(role: str, content: str) -> SimpleNamespace:
    """Stub ChatMessage (matches the real LlamaIndex interface)."""
    return SimpleNamespace(role=role, content=content)


# ---------------------------------------------------------------------------
# Helpers unit tests
# ---------------------------------------------------------------------------


def test_role_str_plain_string() -> None:
    assert _role_str("user") == "user"


def test_role_str_enum_value() -> None:
    role = SimpleNamespace(value="assistant")
    assert _role_str(role) == "assistant"


def test_role_str_human_normalised() -> None:
    assert _role_str("human") == "user"


def test_event_name_plain_string() -> None:
    assert _event_name("llm") == "llm"


def test_event_name_enum_value() -> None:
    et = SimpleNamespace(value="function_call")
    assert _event_name(et) == "function_call"


# ---------------------------------------------------------------------------
# CrewLayerMemoryBuffer
# ---------------------------------------------------------------------------


class TestCrewLayerMemoryBuffer:
    def test_get_returns_chat_messages(self) -> None:
        client = _make_client(messages=[_msg("user", "Hello"), _msg("assistant", "Hi!")])
        buf = CrewLayerMemoryBuffer(client=client, agent_id="a1")
        msgs = buf.get()
        assert len(msgs) == 2
        assert msgs[0].content == "Hello"
        assert msgs[1].content == "Hi!"

    def test_get_passes_session_id_and_limit(self) -> None:
        client = _make_client()
        buf = CrewLayerMemoryBuffer(client=client, agent_id="a1", session_id="s1", limit=20)
        buf.get()
        client.memory.messages.assert_called_once_with("a1", session_id="s1", limit=20)

    def test_get_all_delegates_to_get(self) -> None:
        client = _make_client(messages=[_msg("user", "test")])
        buf = CrewLayerMemoryBuffer(client=client, agent_id="a1")
        all_msgs = buf.get_all()
        get_msgs = buf.get()
        assert len(all_msgs) == len(get_msgs)
        assert all_msgs[0].content == get_msgs[0].content

    def test_get_empty_session(self) -> None:
        client = _make_client(messages=[])
        buf = CrewLayerMemoryBuffer(client=client, agent_id="a1")
        assert buf.get() == []

    def test_put_appends_message(self) -> None:
        client = _make_client()
        buf = CrewLayerMemoryBuffer(client=client, agent_id="a1", session_id="s1")
        buf.put(_chat_msg("user", "Hello there"))
        client.memory.append.assert_called_once_with("a1", "user", "Hello there", session_id="s1")

    def test_put_normalises_enum_role(self) -> None:
        client = _make_client()
        buf = CrewLayerMemoryBuffer(client=client, agent_id="a1")
        buf.put(SimpleNamespace(role=SimpleNamespace(value="assistant"), content="ok"))
        kw = client.memory.append.call_args
        assert kw[0][1] == "assistant"

    def test_put_normalises_human_role(self) -> None:
        client = _make_client()
        buf = CrewLayerMemoryBuffer(client=client, agent_id="a1")
        buf.put(_chat_msg("human", "hi"))
        kw = client.memory.append.call_args
        assert kw[0][1] == "user"

    def test_set_calls_put_for_each(self) -> None:
        client = _make_client()
        buf = CrewLayerMemoryBuffer(client=client, agent_id="a1")
        buf.set([_chat_msg("user", "A"), _chat_msg("assistant", "B"), _chat_msg("user", "C")])
        assert client.memory.append.call_count == 3

    def test_reset_is_noop(self) -> None:
        buf = CrewLayerMemoryBuffer(client=_make_client(), agent_id="a1")
        buf.reset()  # must not raise

    def test_role_str_in_returned_messages(self) -> None:
        client = _make_client(messages=[_msg("human", "Hello")])
        buf = CrewLayerMemoryBuffer(client=client, agent_id="a1")
        msgs = buf.get()
        # role must be normalized to "user"
        assert _role_str(msgs[0].role) == "user"


# ---------------------------------------------------------------------------
# CrewLayerVectorIndex
# ---------------------------------------------------------------------------


class TestCrewLayerVectorIndex:
    def test_insert_calls_extract(self) -> None:
        client = _make_client(extract_ids=["m1", "m2"])
        index = CrewLayerVectorIndex(client=client, agent_id="a1")
        ids = index.insert(SimpleNamespace(text="some document text"))
        assert ids == ["m1", "m2"]
        call_kw = client.memory.extract.call_args[1]
        assert "some document text" in call_kw["conversation"]

    def test_insert_uses_get_content_method(self) -> None:
        client = _make_client(extract_ids=["m1"])
        index = CrewLayerVectorIndex(client=client, agent_id="a1")
        doc = SimpleNamespace(text=None, get_content=lambda: "from get_content")
        index.insert(doc)
        kw = client.memory.extract.call_args[1]
        assert "from get_content" in kw["conversation"]

    def test_insert_falls_back_to_str(self) -> None:
        client = _make_client(extract_ids=["m1"])
        index = CrewLayerVectorIndex(client=client, agent_id="a1")
        doc = SimpleNamespace(text=None)
        index.insert(doc)
        client.memory.extract.assert_called_once()

    def test_similarity_search_returns_items(self) -> None:
        items = [_memory_item("fact A", 0.9), _memory_item("fact B", 0.75)]
        client = _make_client(recall_results=items)
        index = CrewLayerVectorIndex(client=client, agent_id="a1")
        results = index.similarity_search("query")
        assert len(results) == 2
        assert results[0].content == "fact A"

    def test_similarity_search_uses_default_top_k(self) -> None:
        client = _make_client()
        index = CrewLayerVectorIndex(client=client, agent_id="a1", similarity_top_k=6)
        index.similarity_search("q")
        kw = client.memory.recall.call_args[1]
        assert kw["limit"] == 6

    def test_similarity_search_overrides_top_k(self) -> None:
        client = _make_client()
        index = CrewLayerVectorIndex(client=client, agent_id="a1", similarity_top_k=4)
        index.similarity_search("q", top_k=2)
        kw = client.memory.recall.call_args[1]
        assert kw["limit"] == 2

    def test_similarity_search_passes_min_similarity(self) -> None:
        client = _make_client()
        index = CrewLayerVectorIndex(client=client, agent_id="a1", min_similarity=0.5)
        index.similarity_search("q")
        kw = client.memory.recall.call_args[1]
        assert kw["min_similarity"] == pytest.approx(0.5)

    def test_as_query_engine_returns_engine(self) -> None:
        client = _make_client()
        index = CrewLayerVectorIndex(client=client, agent_id="a1")
        engine = index.as_query_engine()
        assert isinstance(engine, CrewLayerQueryEngine)
        assert engine._index is index

    def test_as_query_engine_forwards_session_id(self) -> None:
        client = _make_client()
        index = CrewLayerVectorIndex(client=client, agent_id="a1")
        engine = index.as_query_engine(session_id="sess-x")
        assert engine._session_id == "sess-x"

    def test_as_query_engine_forwards_top_k(self) -> None:
        client = _make_client()
        index = CrewLayerVectorIndex(client=client, agent_id="a1")
        engine = index.as_query_engine(similarity_top_k=8)
        assert engine._similarity_top_k == 8


# ---------------------------------------------------------------------------
# CrewLayerQueryEngine
# ---------------------------------------------------------------------------


class TestCrewLayerQueryEngine:
    def test_query_returns_query_response(self) -> None:
        items = [_memory_item("Result A"), _memory_item("Result B")]
        client = _make_client(recall_results=items)
        index = CrewLayerVectorIndex(client=client, agent_id="a1")
        engine = CrewLayerQueryEngine(index=index)
        resp = engine.query("test question")
        assert isinstance(resp, QueryResponse)
        assert "Result A" in resp.response
        assert "Result B" in resp.response

    def test_query_response_str_is_response_text(self) -> None:
        client = _make_client(recall_results=[_memory_item("answer")])
        index = CrewLayerVectorIndex(client=client, agent_id="a1")
        engine = CrewLayerQueryEngine(index=index)
        resp = engine.query("q")
        assert str(resp) == resp.response

    def test_query_logs_action_with_tool_name(self) -> None:
        client = _make_client(recall_results=[])
        index = CrewLayerVectorIndex(client=client, agent_id="a1")
        engine = CrewLayerQueryEngine(index=index, session_id="s1")
        engine.query("my question")

        client.actions.log.assert_called_once()
        kw = client.actions.log.call_args[1]
        assert kw["tool_name"] == "llamaindex.query"
        assert kw["status"] == "success"
        assert kw["session_id"] == "s1"
        assert kw["input_params"]["query"] == "my question"

    def test_query_logs_results_count(self) -> None:
        items = [_memory_item("x"), _memory_item("y"), _memory_item("z")]
        client = _make_client(recall_results=items)
        index = CrewLayerVectorIndex(client=client, agent_id="a1")
        engine = CrewLayerQueryEngine(index=index)
        engine.query("q")
        kw = client.actions.log.call_args[1]
        assert kw["output_result"]["results_count"] == 3

    def test_query_duration_ms_is_non_negative_int(self) -> None:
        client = _make_client(recall_results=[])
        index = CrewLayerVectorIndex(client=client, agent_id="a1")
        engine = CrewLayerQueryEngine(index=index)
        engine.query("q")
        kw = client.actions.log.call_args[1]
        assert isinstance(kw["duration_ms"], int)
        assert kw["duration_ms"] >= 0

    def test_query_empty_results_gives_empty_response(self) -> None:
        client = _make_client(recall_results=[])
        index = CrewLayerVectorIndex(client=client, agent_id="a1")
        engine = CrewLayerQueryEngine(index=index)
        resp = engine.query("q")
        assert resp.response == ""
        assert resp.source_nodes == []

    def test_query_source_nodes_are_memory_items(self) -> None:
        item = _memory_item("detail", id="m99")
        client = _make_client(recall_results=[item])
        index = CrewLayerVectorIndex(client=client, agent_id="a1")
        engine = CrewLayerQueryEngine(index=index)
        resp = engine.query("q")
        assert resp.source_nodes[0].id == "m99"

    def test_query_overrides_top_k_on_index(self) -> None:
        client = _make_client(recall_results=[])
        index = CrewLayerVectorIndex(client=client, agent_id="a1", similarity_top_k=4)
        engine = CrewLayerQueryEngine(index=index, similarity_top_k=2)
        engine.query("q")
        kw = client.memory.recall.call_args[1]
        assert kw["limit"] == 2

    def test_query_logs_error_and_reraises_on_recall_failure(self) -> None:
        client = _make_client()
        client.memory.recall.side_effect = RuntimeError("db error")
        index = CrewLayerVectorIndex(client=client, agent_id="a1")
        engine = CrewLayerQueryEngine(index=index)
        with pytest.raises(RuntimeError, match="db error"):
            engine.query("q")
        kw = client.actions.log.call_args[1]
        assert kw["status"] == "error"
        assert "db error" in kw["error_msg"]


# ---------------------------------------------------------------------------
# CrewLayerCallbackManager
# ---------------------------------------------------------------------------


class TestCrewLayerCallbackManager:
    def _eid(self) -> str:
        return str(uuid.uuid4())

    def test_on_event_end_llm_logs_action(self) -> None:
        client = MagicMock()
        handler = CrewLayerCallbackManager(client=client, agent_id="a1")
        eid = self._eid()
        handler.on_event_start("llm", payload={}, event_id=eid)
        handler.on_event_end("llm", payload={"response": SimpleNamespace(text="hello")}, event_id=eid)

        client.actions.log.assert_called_once()
        kw = client.actions.log.call_args[1]
        assert kw["tool_name"] == "llamaindex.llm"
        assert kw["status"] == "success"
        assert "hello" in kw["output_result"].get("response", "")

    def test_on_event_end_function_call_logs_action(self) -> None:
        client = MagicMock()
        handler = CrewLayerCallbackManager(client=client, agent_id="a1")
        eid = self._eid()
        handler.on_event_start("function_call", payload={}, event_id=eid)
        handler.on_event_end(
            "function_call",
            payload={"function_call_response": "result"},
            event_id=eid,
        )
        kw = client.actions.log.call_args[1]
        assert kw["tool_name"] == "llamaindex.function_call"

    def test_on_event_end_agent_step_logs_action(self) -> None:
        client = MagicMock()
        handler = CrewLayerCallbackManager(client=client, agent_id="a1")
        eid = self._eid()
        handler.on_event_start("agent_step", payload={}, event_id=eid)
        handler.on_event_end("agent_step", payload={}, event_id=eid)
        kw = client.actions.log.call_args[1]
        assert kw["tool_name"] == "llamaindex.agent_step"

    def test_untracked_event_type_not_logged(self) -> None:
        client = MagicMock()
        handler = CrewLayerCallbackManager(client=client, agent_id="a1")
        eid = self._eid()
        handler.on_event_start("embedding", payload={}, event_id=eid)
        handler.on_event_end("embedding", payload={}, event_id=eid)
        client.actions.log.assert_not_called()

    def test_on_event_end_uses_enum_event_type(self) -> None:
        client = MagicMock()
        handler = CrewLayerCallbackManager(client=client, agent_id="a1")
        eid = self._eid()
        et = SimpleNamespace(value="llm")
        handler.on_event_start(et, payload={}, event_id=eid)
        handler.on_event_end(et, payload={}, event_id=eid)
        kw = client.actions.log.call_args[1]
        assert kw["tool_name"] == "llamaindex.llm"

    def test_duration_ms_is_non_negative_int(self) -> None:
        client = MagicMock()
        handler = CrewLayerCallbackManager(client=client, agent_id="a1")
        eid = self._eid()
        handler.on_event_start("llm", payload={}, event_id=eid)
        handler.on_event_end("llm", payload={}, event_id=eid)
        kw = client.actions.log.call_args[1]
        assert isinstance(kw["duration_ms"], int)
        assert kw["duration_ms"] >= 0

    def test_session_id_forwarded(self) -> None:
        client = MagicMock()
        handler = CrewLayerCallbackManager(client=client, agent_id="a1", session_id="s42")
        eid = self._eid()
        handler.on_event_start("llm", payload={}, event_id=eid)
        handler.on_event_end("llm", payload={}, event_id=eid)
        kw = client.actions.log.call_args[1]
        assert kw["session_id"] == "s42"

    def test_on_event_end_without_prior_start_still_logs(self) -> None:
        """on_event_end with unknown event_id logs with duration_ms=None."""
        client = MagicMock()
        handler = CrewLayerCallbackManager(client=client, agent_id="a1")
        handler.on_event_end("llm", payload={}, event_id="unknown-id")
        client.actions.log.assert_called_once()
        kw = client.actions.log.call_args[1]
        assert kw["duration_ms"] is None

    def test_logging_failure_does_not_propagate(self) -> None:
        """If actions.log raises, the callback must not block the pipeline."""
        client = MagicMock()
        client.actions.log.side_effect = RuntimeError("network down")
        handler = CrewLayerCallbackManager(client=client, agent_id="a1")
        eid = self._eid()
        handler.on_event_start("llm", payload={}, event_id=eid)
        handler.on_event_end("llm", payload={}, event_id=eid)  # must not raise

    def test_start_trace_is_noop(self) -> None:
        handler = CrewLayerCallbackManager(client=MagicMock(), agent_id="a1")
        handler.start_trace("trace-1")  # must not raise

    def test_end_trace_is_noop(self) -> None:
        handler = CrewLayerCallbackManager(client=MagicMock(), agent_id="a1")
        handler.end_trace("trace-1", trace_map={})  # must not raise

    def test_input_extracted_from_start_payload(self) -> None:
        client = MagicMock()
        handler = CrewLayerCallbackManager(client=client, agent_id="a1")
        eid = self._eid()
        last_msg = SimpleNamespace(content="what is 2+2?")
        handler.on_event_start(
            "llm",
            payload={"messages": [last_msg], "model_name": "gpt-4"},
            event_id=eid,
        )
        handler.on_event_end("llm", payload={}, event_id=eid)
        kw = client.actions.log.call_args[1]
        inp = kw["input_params"]
        assert inp.get("message_count") == 1
        assert "what is 2+2?" in inp.get("last_message", "")

    def test_multiple_parallel_events(self) -> None:
        """Two concurrent events with different event_ids log independently."""
        client = MagicMock()
        handler = CrewLayerCallbackManager(client=client, agent_id="a1")
        eid1, eid2 = self._eid(), self._eid()
        handler.on_event_start("llm", payload={}, event_id=eid1)
        handler.on_event_start("function_call", payload={}, event_id=eid2)
        handler.on_event_end("llm", payload={}, event_id=eid1)
        handler.on_event_end("function_call", payload={}, event_id=eid2)

        assert client.actions.log.call_count == 2
        tool_names = {c[1]["tool_name"] for c in client.actions.log.call_args_list}
        assert "llamaindex.llm" in tool_names
        assert "llamaindex.function_call" in tool_names
