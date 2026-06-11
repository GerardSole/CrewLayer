"""Tests for sdk/crewlayer/integrations/langchain.py.

All tests use mock clients — no real LangChain or CrewLayer server needed.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from crewlayer.integrations.langchain import (
    AgentLayerCallbackHandler,
    AgentLayerMemory,
    AgentLayerVectorStore,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_client(
    messages=None,
    recall_results=None,
    extract_ids=None,
) -> MagicMock:
    """Return a mock CrewLayerClient with sane defaults."""
    client = MagicMock()

    # memory.messages()
    msg_list = messages or []
    client.memory.messages.return_value = SimpleNamespace(messages=msg_list)

    # memory.recall()
    results = recall_results or []
    client.memory.recall.return_value = SimpleNamespace(results=results)

    # memory.extract()
    ids = extract_ids or ["mem-1"]
    client.memory.extract.return_value = SimpleNamespace(memory_ids=ids)

    return client


def _msg(role: str, content: str) -> SimpleNamespace:
    return SimpleNamespace(role=role, content=content)


def _recall_item(
    content: str,
    similarity: float = 0.9,
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


# ---------------------------------------------------------------------------
# AgentLayerMemory
# ---------------------------------------------------------------------------


class TestAgentLayerMemory:
    def test_memory_variables_contains_key(self) -> None:
        mem = AgentLayerMemory(client=_make_client(), agent_id="a1", memory_key="chat_history")
        assert mem.memory_variables == ["chat_history"]

    def test_load_returns_human_ai_messages(self) -> None:
        client = _make_client(
            messages=[_msg("user", "Hi"), _msg("assistant", "Hello!")]
        )
        mem = AgentLayerMemory(client=client, agent_id="a1")
        result = mem.load_memory_variables({})
        msgs = result["history"]
        assert len(msgs) == 2
        assert msgs[0].content == "Hi"
        assert msgs[1].content == "Hello!"

    def test_load_human_role_variants(self) -> None:
        """Both 'user' and 'human' roles should produce HumanMessage."""
        client = _make_client(
            messages=[_msg("human", "Hello"), _msg("user", "World")]
        )
        mem = AgentLayerMemory(client=client, agent_id="a1", return_messages=True)
        msgs = mem.load_memory_variables({})["history"]
        from crewlayer.integrations.langchain import HumanMessage
        for m in msgs:
            assert isinstance(m, HumanMessage)

    def test_load_string_mode(self) -> None:
        client = _make_client(
            messages=[_msg("user", "Hi"), _msg("assistant", "Hello!")]
        )
        mem = AgentLayerMemory(client=client, agent_id="a1", return_messages=False)
        result = mem.load_memory_variables({})["history"]
        assert "user: Hi" in result
        assert "assistant: Hello!" in result

    def test_load_empty_session(self) -> None:
        client = _make_client(messages=[])
        mem = AgentLayerMemory(client=client, agent_id="a1")
        assert mem.load_memory_variables({})["history"] == []

    def test_save_context_appends_both_turns(self) -> None:
        client = _make_client()
        mem = AgentLayerMemory(client=client, agent_id="a1", session_id="s1")
        mem.save_context({"input": "Hi"}, {"output": "Hello!"})

        assert client.memory.append.call_count == 2
        first_call, second_call = client.memory.append.call_args_list
        assert first_call == call("a1", "user", "Hi", session_id="s1")
        assert second_call == call("a1", "assistant", "Hello!", session_id="s1")

    def test_save_context_custom_keys(self) -> None:
        client = _make_client()
        mem = AgentLayerMemory(
            client=client, agent_id="a1", input_key="question", output_key="answer"
        )
        mem.save_context({"question": "2+2?", "other": "x"}, {"answer": "4"})
        first, second = client.memory.append.call_args_list
        assert first[0][2] == "2+2?"
        assert second[0][2] == "4"

    def test_save_context_missing_output_key(self) -> None:
        """When output dict is empty, only the input turn is saved."""
        client = _make_client()
        mem = AgentLayerMemory(client=client, agent_id="a1")
        mem.save_context({"input": "Hi"}, {})
        assert client.memory.append.call_count == 1

    def test_clear_is_noop(self) -> None:
        mem = AgentLayerMemory(client=_make_client(), agent_id="a1")
        mem.clear()  # must not raise

    def test_messages_called_with_session_id(self) -> None:
        client = _make_client()
        mem = AgentLayerMemory(client=client, agent_id="a1", session_id="xyz")
        mem.load_memory_variables({})
        client.memory.messages.assert_called_once_with("a1", session_id="xyz")


# ---------------------------------------------------------------------------
# AgentLayerVectorStore
# ---------------------------------------------------------------------------


class TestAgentLayerVectorStore:
    def test_similarity_search_returns_documents(self) -> None:
        items = [_recall_item("Python dev", 0.95), _recall_item("dark mode", 0.80)]
        client = _make_client(recall_results=items)
        store = AgentLayerVectorStore(client=client, agent_id="a1")
        docs = store.similarity_search("preferences")
        assert len(docs) == 2
        assert docs[0].page_content == "Python dev"
        assert docs[0].metadata["similarity"] == 0.95

    def test_similarity_search_uses_k_param(self) -> None:
        client = _make_client(recall_results=[])
        store = AgentLayerVectorStore(client=client, agent_id="a1", k=4)
        store.similarity_search("q", k=7)
        client.memory.recall.assert_called_once_with("a1", "q", limit=7, min_similarity=0.0)

    def test_similarity_search_uses_default_k(self) -> None:
        client = _make_client(recall_results=[])
        store = AgentLayerVectorStore(client=client, agent_id="a1", k=3)
        store.similarity_search("q")
        client.memory.recall.assert_called_once_with("a1", "q", limit=3, min_similarity=0.0)

    def test_similarity_search_with_score(self) -> None:
        items = [_recall_item("content", 0.88)]
        client = _make_client(recall_results=items)
        store = AgentLayerVectorStore(client=client, agent_id="a1")
        results = store.similarity_search_with_score("q")
        assert len(results) == 1
        doc, score = results[0]
        assert doc.page_content == "content"
        assert score == pytest.approx(0.88)

    def test_similarity_search_with_score_null_similarity(self) -> None:
        item = _recall_item("x", similarity=None)
        client = _make_client(recall_results=[item])
        store = AgentLayerVectorStore(client=client, agent_id="a1")
        _, score = store.similarity_search_with_score("q")[0]
        assert score == 0.0

    def test_add_texts_calls_extract_per_text(self) -> None:
        client = _make_client(extract_ids=["id-1"])
        store = AgentLayerVectorStore(client=client, agent_id="a1")
        ids = store.add_texts(["text A", "text B"])
        assert client.memory.extract.call_count == 2
        assert len(ids) == 2

    def test_add_texts_embeds_prompt_prefix(self) -> None:
        client = _make_client()
        store = AgentLayerVectorStore(client=client, agent_id="a1")
        store.add_texts(["hello world"])
        call_kwargs = client.memory.extract.call_args
        assert "hello world" in call_kwargs[1]["conversation"]

    def test_from_texts_factory(self) -> None:
        client = _make_client(extract_ids=["m1"])
        store = AgentLayerVectorStore.from_texts(
            ["fact one", "fact two"],
            embedding=None,
            client=client,
            agent_id="a1",
        )
        assert isinstance(store, AgentLayerVectorStore)
        assert client.memory.extract.call_count == 2

    def test_metadata_fields_present(self) -> None:
        item = _recall_item("content", tags=["python"], importance=0.9)
        client = _make_client(recall_results=[item])
        store = AgentLayerVectorStore(client=client, agent_id="a1")
        doc = store.similarity_search("q")[0]
        assert doc.metadata["tags"] == ["python"]
        assert doc.metadata["importance"] == 0.9
        assert "memory_id" in doc.metadata


# ---------------------------------------------------------------------------
# AgentLayerCallbackHandler
# ---------------------------------------------------------------------------


class TestAgentLayerCallbackHandler:
    def _run_id(self) -> uuid.UUID:
        return uuid.uuid4()

    def test_on_tool_end_logs_success(self) -> None:
        client = _make_client()
        handler = AgentLayerCallbackHandler(client=client, agent_id="a1")
        rid = self._run_id()
        handler.on_tool_start({"name": "search"}, "query text", run_id=rid)
        handler.on_tool_end("result text", run_id=rid)

        client.actions.log.assert_called_once()
        kw = client.actions.log.call_args[1]
        assert kw["tool_name"] == "search"
        assert kw["status"] == "success"
        assert "query text" in kw["input_params"]["input"]
        assert "result text" in kw["output_result"]["output"]

    def test_on_tool_error_logs_error_status(self) -> None:
        client = _make_client()
        handler = AgentLayerCallbackHandler(client=client, agent_id="a1")
        rid = self._run_id()
        handler.on_tool_start({"name": "calculator"}, "1+1", run_id=rid)
        handler.on_tool_error(ValueError("oops"), run_id=rid)

        kw = client.actions.log.call_args[1]
        assert kw["status"] == "error"
        assert kw["tool_name"] == "calculator"
        assert "oops" in kw["error_msg"]

    def test_duration_ms_is_positive_integer(self) -> None:
        client = _make_client()
        handler = AgentLayerCallbackHandler(client=client, agent_id="a1")
        rid = self._run_id()
        handler.on_tool_start({"name": "t"}, "x", run_id=rid)
        handler.on_tool_end("y", run_id=rid)

        kw = client.actions.log.call_args[1]
        assert isinstance(kw["duration_ms"], int)
        assert kw["duration_ms"] >= 0

    def test_session_id_forwarded(self) -> None:
        client = _make_client()
        handler = AgentLayerCallbackHandler(client=client, agent_id="a1", session_id="sess-1")
        rid = self._run_id()
        handler.on_tool_start({}, "x", run_id=rid)
        handler.on_tool_end("y", run_id=rid)

        kw = client.actions.log.call_args[1]
        assert kw["session_id"] == "sess-1"

    def test_on_tool_end_without_prior_start(self) -> None:
        """on_tool_end with unknown run_id should still log (gracefully)."""
        client = _make_client()
        handler = AgentLayerCallbackHandler(client=client, agent_id="a1")
        handler.on_tool_end("result", run_id=uuid.uuid4())
        assert client.actions.log.called

    def test_on_tool_error_without_prior_start(self) -> None:
        client = _make_client()
        handler = AgentLayerCallbackHandler(client=client, agent_id="a1")
        handler.on_tool_error(RuntimeError("fail"), run_id=uuid.uuid4())
        assert client.actions.log.called

    def test_multiple_parallel_tools(self) -> None:
        """Two concurrent tool runs with different run_ids log independently."""
        client = _make_client()
        handler = AgentLayerCallbackHandler(client=client, agent_id="a1")
        rid1, rid2 = self._run_id(), self._run_id()
        handler.on_tool_start({"name": "tool1"}, "in1", run_id=rid1)
        handler.on_tool_start({"name": "tool2"}, "in2", run_id=rid2)
        handler.on_tool_end("out1", run_id=rid1)
        handler.on_tool_end("out2", run_id=rid2)

        assert client.actions.log.call_count == 2
        calls = {c[1]["tool_name"]: c[1] for c in client.actions.log.call_args_list}
        assert "in1" in calls["tool1"]["input_params"]["input"]
        assert "in2" in calls["tool2"]["input_params"]["input"]

    def test_no_run_id_uses_fallback_tool_name(self) -> None:
        client = _make_client()
        handler = AgentLayerCallbackHandler(client=client, agent_id="a1")
        handler.on_tool_end("result", run_id=None, name="my_tool")
        kw = client.actions.log.call_args[1]
        assert kw["tool_name"] == "my_tool"
