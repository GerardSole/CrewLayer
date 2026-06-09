"""Tests for the CrewLayer MCP server.

Verifies that each tool:
  1. Makes the correct HTTP request (method, path, payload)
  2. Returns valid JSON-serialised output (MCP tools must return strings)
  3. Propagates API errors as RuntimeError
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

# ---------------------------------------------------------------------------
# Load mcp/server.py without touching sys.path
# ---------------------------------------------------------------------------

_SERVER_PATH = pathlib.Path(__file__).parent.parent / "mcp" / "server.py"
_spec = importlib.util.spec_from_file_location("crewlayer_mcp_server", _SERVER_PATH)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

memory_recall: Any = _mod.memory_recall
memory_append: Any = _mod.memory_append
memory_extract: Any = _mod.memory_extract
action_log: Any = _mod.action_log
action_list: Any = _mod.action_list
context_write: Any = _mod.context_write
context_read: Any = _mod.context_read
agent_status: Any = _mod.agent_status
agent_set_status: Any = _mod.agent_set_status


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _response(data: Any, status_code: int = 200) -> MagicMock:
    """Build a mock httpx.Response."""
    r = MagicMock(spec=httpx.Response)
    r.json.return_value = data
    r.status_code = status_code
    r.is_success = status_code < 400
    r.text = json.dumps(data)
    r.request = MagicMock()
    r.request.method = "GET"
    r.request.url = "http://localhost:8000/test"
    return r


def _http_ctx(mock_client: MagicMock) -> MagicMock:
    """Return a mock _http() context manager that yields mock_client."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_client)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


# ---------------------------------------------------------------------------
# memory_recall
# ---------------------------------------------------------------------------


def test_memory_recall_correct_request() -> None:
    data = [{"content": "the user prefers Python", "similarity": 0.97}]
    mock_client = MagicMock()
    mock_client.post.return_value = _response(data)

    with patch.object(_mod, "_http", return_value=_http_ctx(mock_client)):
        result = memory_recall("agent-abc", "language preference", 5)

    mock_client.post.assert_called_once_with(
        "/v1/agents/agent-abc/memory/recall",
        json={"query": "language preference", "limit": 5},
    )
    assert json.loads(result) == data


def test_memory_recall_returns_json_string() -> None:
    mock_client = MagicMock()
    mock_client.post.return_value = _response([])

    with patch.object(_mod, "_http", return_value=_http_ctx(mock_client)):
        result = memory_recall("x", "q")

    assert isinstance(result, str)
    json.loads(result)  # must be valid JSON


def test_memory_recall_default_top_k() -> None:
    mock_client = MagicMock()
    mock_client.post.return_value = _response([])

    with patch.object(_mod, "_http", return_value=_http_ctx(mock_client)):
        memory_recall("a", "q")

    _, kwargs = mock_client.post.call_args
    assert kwargs["json"]["limit"] == 10


# ---------------------------------------------------------------------------
# memory_append
# ---------------------------------------------------------------------------


def test_memory_append_correct_request() -> None:
    data = {"session_id": "sess-1", "count": 3}
    mock_client = MagicMock()
    mock_client.post.return_value = _response(data)

    with patch.object(_mod, "_http", return_value=_http_ctx(mock_client)):
        result = memory_append("agent-1", "sess-1", "user", "hello")

    mock_client.post.assert_called_once_with(
        "/v1/agents/agent-1/memory/messages",
        params={"session_id": "sess-1"},
        json={"role": "user", "content": "hello"},
    )
    assert json.loads(result) == data


# ---------------------------------------------------------------------------
# memory_extract
# ---------------------------------------------------------------------------


def test_memory_extract_closes_session() -> None:
    data = {"id": "sess-2", "status": "closed", "memories_extracted": 4}
    mock_client = MagicMock()
    mock_client.post.return_value = _response(data)

    with patch.object(_mod, "_http", return_value=_http_ctx(mock_client)):
        result = memory_extract("agent-2", "sess-2")

    mock_client.post.assert_called_once_with("/v1/sessions/sess-2/close")
    assert json.loads(result)["memories_extracted"] == 4


# ---------------------------------------------------------------------------
# action_log
# ---------------------------------------------------------------------------


def test_action_log_minimal() -> None:
    data = {"id": "act-1", "tool_name": "search"}
    mock_client = MagicMock()
    mock_client.post.return_value = _response(data)

    with patch.object(_mod, "_http", return_value=_http_ctx(mock_client)):
        result = action_log(
            "agent-3",
            "search",
            {"q": "foo"},
            {"results": []},
            "success",
        )

    _, kwargs = mock_client.post.call_args
    assert kwargs["json"]["tool_name"] == "search"
    assert kwargs["json"]["status"] == "success"
    assert "duration_ms" not in kwargs["json"]
    assert "session_id" not in kwargs["json"]
    assert json.loads(result)["id"] == "act-1"


def test_action_log_with_optional_fields() -> None:
    mock_client = MagicMock()
    mock_client.post.return_value = _response({})

    with patch.object(_mod, "_http", return_value=_http_ctx(mock_client)):
        action_log("a", "tool", {}, {}, "error", duration_ms=42, session_id="sess-9")

    _, kwargs = mock_client.post.call_args
    assert kwargs["json"]["duration_ms"] == 42
    assert kwargs["json"]["session_id"] == "sess-9"


# ---------------------------------------------------------------------------
# action_list
# ---------------------------------------------------------------------------


def test_action_list_default_params() -> None:
    data = {"items": [], "next_cursor": None}
    mock_client = MagicMock()
    mock_client.get.return_value = _response(data)

    with patch.object(_mod, "_http", return_value=_http_ctx(mock_client)):
        result = action_list("agent-4")

    _, kwargs = mock_client.get.call_args
    assert kwargs["params"] == {"limit": 50}
    assert json.loads(result) == data


def test_action_list_with_filters() -> None:
    mock_client = MagicMock()
    mock_client.get.return_value = _response({"items": []})

    with patch.object(_mod, "_http", return_value=_http_ctx(mock_client)):
        action_list("agent-4", tool="search", status="error", limit=10, cursor="cur123")

    _, kwargs = mock_client.get.call_args
    assert kwargs["params"]["tool"] == "search"
    assert kwargs["params"]["status"] == "error"
    assert kwargs["params"]["limit"] == 10
    assert kwargs["params"]["cursor"] == "cur123"


# ---------------------------------------------------------------------------
# context_write
# ---------------------------------------------------------------------------


def test_context_write_correct_request() -> None:
    data = {"namespace": "proj", "key": "config", "value": {"debug": True}, "version": 1}
    mock_client = MagicMock()
    mock_client.put.return_value = _response(data)

    with patch.object(_mod, "_http", return_value=_http_ctx(mock_client)):
        result = context_write("proj", "config", {"debug": True})

    mock_client.put.assert_called_once_with(
        "/v1/context/proj/config",
        json={"value": {"debug": True}},
    )
    assert json.loads(result)["version"] == 1


# ---------------------------------------------------------------------------
# context_read
# ---------------------------------------------------------------------------


def test_context_read_correct_request() -> None:
    data = {"namespace": "proj", "key": "config", "value": "hello"}
    mock_client = MagicMock()
    mock_client.get.return_value = _response(data)

    with patch.object(_mod, "_http", return_value=_http_ctx(mock_client)):
        result = context_read("proj", "config")

    mock_client.get.assert_called_once_with("/v1/context/proj/config")
    assert json.loads(result)["value"] == "hello"


# ---------------------------------------------------------------------------
# agent_status
# ---------------------------------------------------------------------------


def test_agent_status_correct_request() -> None:
    data = {
        "agent_id": "agent-5",
        "status": "working",
        "current_session_id": "sess-5",
        "updated_at": "2026-06-09T10:00:00+00:00",
    }
    mock_client = MagicMock()
    mock_client.get.return_value = _response(data)

    with patch.object(_mod, "_http", return_value=_http_ctx(mock_client)):
        result = agent_status("agent-5")

    mock_client.get.assert_called_once_with("/v1/agents/agent-5/status")
    body = json.loads(result)
    assert body["status"] == "working"
    assert body["current_session_id"] == "sess-5"


# ---------------------------------------------------------------------------
# agent_set_status
# ---------------------------------------------------------------------------


def test_agent_set_status_correct_request() -> None:
    data = {
        "agent_id": "agent-6",
        "status": "error",
        "current_session_id": None,
        "updated_at": "2026-06-09T10:00:00+00:00",
    }
    mock_client = MagicMock()
    mock_client.patch.return_value = _response(data)

    with patch.object(_mod, "_http", return_value=_http_ctx(mock_client)):
        result = agent_set_status("agent-6", "error")

    mock_client.patch.assert_called_once_with(
        "/v1/agents/agent-6/status",
        json={"status": "error"},
    )
    assert json.loads(result)["status"] == "error"


def test_agent_set_status_with_session_id() -> None:
    mock_client = MagicMock()
    mock_client.patch.return_value = _response({})

    with patch.object(_mod, "_http", return_value=_http_ctx(mock_client)):
        agent_set_status("agent-7", "working", session_id="sess-7")

    _, kwargs = mock_client.patch.call_args
    assert kwargs["json"]["session_id"] == "sess-7"


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------


def test_api_error_raises_runtime_error() -> None:
    """Non-2xx responses must raise RuntimeError so MCP surfaces them as tool errors."""
    error_resp = _response({"detail": "Not found"}, status_code=404)
    mock_client = MagicMock()
    mock_client.get.return_value = error_resp

    with patch.object(_mod, "_http", return_value=_http_ctx(mock_client)):
        with pytest.raises(RuntimeError, match="404"):
            agent_status("nonexistent")


def test_all_tool_results_are_strings() -> None:
    """Every MCP tool must return a str (MCP protocol requirement)."""
    mock_client = MagicMock()
    mock_client.get.return_value = _response({"status": "idle"})
    mock_client.patch.return_value = _response({"status": "idle"})
    mock_client.post.return_value = _response([])
    mock_client.put.return_value = _response({})

    with patch.object(_mod, "_http", return_value=_http_ctx(mock_client)):
        results = [
            agent_status("a"),
            agent_set_status("a", "idle"),
            memory_recall("a", "q"),
            memory_append("a", "s", "user", "hi"),
            memory_extract("a", "s"),
            action_list("a"),
            context_write("ns", "k", "v"),
            context_read("ns", "k"),
        ]

    for r in results:
        assert isinstance(r, str), f"Expected str, got {type(r)}"
        json.loads(r)  # must be valid JSON
