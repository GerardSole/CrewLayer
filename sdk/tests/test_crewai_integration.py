"""Tests for sdk/crewlayer/integrations/crewai.py.

All tests use mock clients — no real CrewAI or CrewLayer server needed.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from crewlayer.integrations.crewai import AgentLayerMemoryProvider, AgentLayerTaskLogger


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_client(recall_results=None) -> MagicMock:
    client = MagicMock()
    results = recall_results or []
    client.memory.recall.return_value = SimpleNamespace(results=results)
    return client


def _recall_item(
    content: str,
    similarity: float = 0.85,
    importance: float = 0.6,
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
# AgentLayerMemoryProvider
# ---------------------------------------------------------------------------


class TestAgentLayerMemoryProvider:
    def test_save_calls_memory_append(self) -> None:
        client = _make_client()
        provider = AgentLayerMemoryProvider(client=client, agent_id="a1", session_id="s1")
        provider.save("User prefers dark mode", metadata={"source": "chat"})

        client.memory.append.assert_called_once_with(
            "a1",
            role="assistant",
            content="User prefers dark mode",
            session_id="s1",
            metadata={"source": "chat"},
        )

    def test_save_no_metadata_defaults_to_empty_dict(self) -> None:
        client = _make_client()
        provider = AgentLayerMemoryProvider(client=client, agent_id="a1")
        provider.save("some fact")
        kw = client.memory.append.call_args[1]
        assert kw["metadata"] == {}

    def test_save_converts_value_to_string(self) -> None:
        client = _make_client()
        provider = AgentLayerMemoryProvider(client=client, agent_id="a1")
        provider.save(42)
        kw = client.memory.append.call_args[1]
        assert kw["content"] == "42"

    def test_search_returns_formatted_dicts(self) -> None:
        items = [
            _recall_item("Python dev", 0.9, importance=0.8, tags=["python"], id="m1"),
            _recall_item("dark mode fan", 0.7),
        ]
        client = _make_client(recall_results=items)
        provider = AgentLayerMemoryProvider(client=client, agent_id="a1")
        results = provider.search("programming preferences")

        assert len(results) == 2
        assert results[0]["id"] == "m1"
        assert results[0]["memory"] == "Python dev"
        assert results[0]["score"] == pytest.approx(0.9)
        assert results[0]["metadata"]["importance"] == 0.8
        assert results[0]["metadata"]["tags"] == ["python"]

    def test_search_uses_default_recall_limit(self) -> None:
        client = _make_client()
        provider = AgentLayerMemoryProvider(client=client, agent_id="a1", recall_limit=7)
        provider.search("query")
        kw = client.memory.recall.call_args[1]
        assert kw["limit"] == 7

    def test_search_overrides_limit(self) -> None:
        client = _make_client()
        provider = AgentLayerMemoryProvider(client=client, agent_id="a1", recall_limit=5)
        provider.search("q", limit=3)
        kw = client.memory.recall.call_args[1]
        assert kw["limit"] == 3

    def test_search_overrides_score_threshold(self) -> None:
        client = _make_client()
        provider = AgentLayerMemoryProvider(client=client, agent_id="a1", min_similarity=0.35)
        provider.search("q", score_threshold=0.6)
        kw = client.memory.recall.call_args[1]
        assert kw["min_similarity"] == pytest.approx(0.6)

    def test_search_uses_default_min_similarity(self) -> None:
        client = _make_client()
        provider = AgentLayerMemoryProvider(client=client, agent_id="a1", min_similarity=0.4)
        provider.search("q")
        kw = client.memory.recall.call_args[1]
        assert kw["min_similarity"] == pytest.approx(0.4)

    def test_search_null_similarity_defaults_to_zero(self) -> None:
        item = _recall_item("x", similarity=None)
        client = _make_client(recall_results=[item])
        provider = AgentLayerMemoryProvider(client=client, agent_id="a1")
        results = provider.search("q")
        assert results[0]["score"] == 0.0

    def test_search_empty_results(self) -> None:
        client = _make_client(recall_results=[])
        provider = AgentLayerMemoryProvider(client=client, agent_id="a1")
        assert provider.search("nothing") == []

    def test_reset_is_noop(self) -> None:
        provider = AgentLayerMemoryProvider(client=_make_client(), agent_id="a1")
        provider.reset()  # must not raise

    def test_search_passes_agent_id(self) -> None:
        client = _make_client()
        provider = AgentLayerMemoryProvider(client=client, agent_id="my-agent")
        provider.search("test query")
        args = client.memory.recall.call_args[0]
        assert args[0] == "my-agent"
        assert args[1] == "test query"


# ---------------------------------------------------------------------------
# AgentLayerTaskLogger
# ---------------------------------------------------------------------------


class TestAgentLayerTaskLogger:
    def _task_output(self, name="task name", raw="task result") -> SimpleNamespace:
        return SimpleNamespace(name=name, raw=raw, description=None)

    def test_logs_action_on_call(self) -> None:
        client = MagicMock()
        logger = AgentLayerTaskLogger(client=client, agent_id="a1")
        output = self._task_output("analyze data", "done")
        logger(output)

        client.actions.log.assert_called_once()
        args = client.actions.log.call_args
        assert args[0][0] == "a1"
        kw = args[1]
        assert kw["tool_name"] == "analyze data"
        assert kw["status"] == "success"
        assert "done" in kw["output_result"]["output"]

    def test_returns_task_output_unchanged(self) -> None:
        client = MagicMock()
        logger = AgentLayerTaskLogger(client=client, agent_id="a1")
        output = self._task_output()
        result = logger(output)
        assert result is output

    def test_session_id_forwarded(self) -> None:
        client = MagicMock()
        logger = AgentLayerTaskLogger(client=client, agent_id="a1", session_id="s99")
        logger(self._task_output())
        kw = client.actions.log.call_args[1]
        assert kw["session_id"] == "s99"

    def test_falls_back_to_description_when_name_missing(self) -> None:
        client = MagicMock()
        logger = AgentLayerTaskLogger(client=client, agent_id="a1")
        output = SimpleNamespace(name=None, description="Analyze feedback", raw="ok")
        logger(output)
        kw = client.actions.log.call_args[1]
        assert kw["tool_name"] == "Analyze feedback"

    def test_falls_back_to_default_tool_name(self) -> None:
        client = MagicMock()
        logger = AgentLayerTaskLogger(client=client, agent_id="a1")
        output = SimpleNamespace(name=None, description=None, raw="something")
        logger(output)
        kw = client.actions.log.call_args[1]
        assert kw["tool_name"] == "crewai_task"

    def test_tool_name_truncated_to_100_chars(self) -> None:
        client = MagicMock()
        logger = AgentLayerTaskLogger(client=client, agent_id="a1")
        long_name = "x" * 200
        output = SimpleNamespace(name=long_name, raw="result")
        logger(output)
        kw = client.actions.log.call_args[1]
        assert len(kw["tool_name"]) == 100

    def test_logging_failure_does_not_propagate(self) -> None:
        """If actions.log raises, the callback must swallow the exception."""
        client = MagicMock()
        client.actions.log.side_effect = RuntimeError("network error")
        logger = AgentLayerTaskLogger(client=client, agent_id="a1")
        result = logger(self._task_output())  # must not raise
        assert result is not None

    def test_raw_output_used_when_available(self) -> None:
        client = MagicMock()
        logger = AgentLayerTaskLogger(client=client, agent_id="a1")
        output = SimpleNamespace(name="t", raw="raw output text")
        logger(output)
        kw = client.actions.log.call_args[1]
        assert "raw output text" in kw["output_result"]["output"]

    def test_str_fallback_when_raw_missing(self) -> None:
        client = MagicMock()
        logger = AgentLayerTaskLogger(client=client, agent_id="a1")
        output = SimpleNamespace(name="task", raw=None)
        output.__str__ = lambda self: "str fallback"
        logger(output)
        # Should not raise; output_result contains some string representation
        kw = client.actions.log.call_args[1]
        assert isinstance(kw["output_result"]["output"], str)

    def test_input_params_always_empty_dict(self) -> None:
        client = MagicMock()
        logger = AgentLayerTaskLogger(client=client, agent_id="a1")
        logger(self._task_output())
        kw = client.actions.log.call_args[1]
        assert kw["input_params"] == {}
