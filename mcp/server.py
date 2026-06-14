"""CrewLayer MCP Server.

Exposes the CrewLayer REST API as MCP tools so Claude can interact with
agents, memory, actions, and shared context directly without writing HTTP code.

Every tool call is automatically logged to CrewLayer actions and the agent
status is updated to "working" / "idle" via the @auto_log decorator.

Environment variables:
    CREWLAYER_API_KEY   API key with appropriate scopes (required)
    CREWLAYER_BASE_URL  Base URL of the CrewLayer API (default: http://localhost:8000)
    MCP_TRANSPORT       Transport to use: stdio (default) | sse

Usage:
    # stdio — Claude Desktop / Claude Code:
    python mcp/server.py

    # SSE — Docker / remote service:
    MCP_TRANSPORT=sse python mcp/server.py
"""
from __future__ import annotations

import functools
import inspect
import json
import os
import time
from typing import Any, Literal, get_args

import httpx
from mcp.server.fastmcp import FastMCP

CREWLAYER_BASE_URL: str = os.environ.get("CREWLAYER_BASE_URL", "http://localhost:8000")
CREWLAYER_API_KEY: str = os.environ.get("CREWLAYER_API_KEY", "")

_TransportT = Literal["stdio", "sse", "streamable-http"]
_raw_transport = os.environ.get("MCP_TRANSPORT", "stdio")
_TRANSPORT: _TransportT = (
    _raw_transport if _raw_transport in get_args(_TransportT) else "stdio"  # type: ignore[assignment]
)

mcp = FastMCP(
    "CrewLayer",
    instructions=(
        "CrewLayer is a stateful backend for AI agents. "
        "Use these tools to store and recall memories, log actions, "
        "read/write shared context, and manage agent runtime status. "
        "Always pass agent UUIDs as strings."
    ),
    host="0.0.0.0",
    port=8001,
)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _http() -> httpx.Client:
    return httpx.Client(
        base_url=CREWLAYER_BASE_URL,
        headers={"X-API-Key": CREWLAYER_API_KEY},
        timeout=30.0,
    )


def _check(response: httpx.Response) -> Any:
    if not response.is_success:
        raise RuntimeError(
            f"CrewLayer API {response.request.method} {response.request.url} "
            f"→ {response.status_code}: {response.text}"
        )
    return response.json()


def _set_status(agent_id: str, status: str) -> None:
    """Update agent status; never raises so it never blocks the calling tool."""
    try:
        with _http() as c:
            c.patch(f"/v1/agents/{agent_id}/status", json={"status": status})
    except Exception:
        pass


def _to_output_dict(raw: str | None) -> dict[str, Any]:
    """Parse a JSON string result into a dict suitable for action logging."""
    if raw is None:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
        return {"items": parsed}
    except (json.JSONDecodeError, TypeError):
        return {"raw": str(raw)}


def _log_action(
    agent_id: str,
    tool_name: str,
    input_params: dict[str, Any],
    output_result: dict[str, Any],
    status: str,
    duration_ms: int,
) -> None:
    """Fire-and-forget action log to CrewLayer; never raises."""
    try:
        with _http() as c:
            c.post(
                f"/v1/agents/{agent_id}/actions",
                json={
                    "tool_name": tool_name,
                    "input_params": input_params,
                    "output_result": output_result,
                    "status": status,
                    "duration_ms": duration_ms,
                },
            )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# @auto_log decorator
# ---------------------------------------------------------------------------


def auto_log(fn: Any) -> Any:
    """Decorator that wraps an MCP tool with automatic action logging.

    For every call it:
      1. Reads ``agent_id`` from the call arguments (may be None).
      2. Sets the agent to ``working`` before execution (if agent_id present).
      3. Executes the tool and measures wall-clock duration.
      4. Logs the call to CrewLayer actions with tool_name, input_params,
         output_result, duration_ms, and status (``success`` | ``error``).
      5. Sets the agent back to ``idle`` in a finally block.

    FastMCP uses ``inspect.signature`` for schema generation; ``functools.wraps``
    preserves ``__wrapped__`` so the original signature is visible.
    """
    sig = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        all_params: dict[str, Any] = dict(bound.arguments)

        agent_id: str | None = all_params.get("agent_id")
        tool_name: str = fn.__name__

        if agent_id:
            _set_status(agent_id, "working")

        start = time.monotonic()
        output_dict: dict[str, Any] = {}
        exc: BaseException | None = None

        try:
            result = fn(*args, **kwargs)
            output_dict = _to_output_dict(result)
            return result
        except Exception as e:
            exc = e
            output_dict = {"error": str(e)}
            raise
        finally:
            duration_ms = int((time.monotonic() - start) * 1000)
            action_status = "error" if exc is not None else "success"
            if agent_id:
                _log_action(
                    agent_id=agent_id,
                    tool_name=tool_name,
                    input_params=all_params,
                    output_result=output_dict,
                    status=action_status,
                    duration_ms=duration_ms,
                )
                _set_status(agent_id, "idle")

    return wrapper


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


@mcp.tool()
@auto_log
def memory_recall(agent_id: str, query: str, top_k: int = 10) -> str:
    """Search long-term memories for an agent using semantic similarity.

    Args:
        agent_id: UUID of the agent whose memories to search.
        query: Natural language query for semantic search.
        top_k: Maximum number of memories to return (1–100, default 10).

    Returns:
        JSON list of matching memory objects with content and similarity scores.
    """
    with _http() as c:
        data = _check(c.post(
            f"/v1/agents/{agent_id}/memory/recall",
            json={"query": query, "limit": top_k},
        ))
    return json.dumps(data)


@mcp.tool()
@auto_log
def memory_append(agent_id: str, session_id: str, role: str, content: str) -> str:
    """Append a message to an agent's short-term (Redis) memory for a session.

    Args:
        agent_id: UUID of the agent.
        session_id: UUID of the active session.
        role: Message role — 'user', 'assistant', or 'system'.
        content: Message text to append.

    Returns:
        JSON confirmation with session_id and updated message count.
    """
    with _http() as c:
        data = _check(c.post(
            f"/v1/agents/{agent_id}/memory/messages",
            params={"session_id": session_id},
            json={"role": role, "content": content},
        ))
    return json.dumps(data)


@mcp.tool()
@auto_log
def memory_extract(agent_id: str, session_id: str) -> str:
    """Close a session and extract long-term memories from its conversation history.

    Claude processes all messages in the session, identifies important facts,
    and persists them as long-term vector memories. The session is marked closed.

    Args:
        agent_id: UUID of the agent (used for status tracking; not sent to the API).
        session_id: UUID of the active session to close and extract from.

    Returns:
        JSON with the closed session record and count of extracted memories.
    """
    with _http() as c:
        data = _check(c.post(f"/v1/sessions/{session_id}/close"))
    return json.dumps(data)


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


@mcp.tool()
@auto_log
def action_log(
    agent_id: str,
    tool_name: str,
    input_params: dict[str, Any],
    output_result: dict[str, Any],
    status: str,
    duration_ms: int | None = None,
    session_id: str | None = None,
) -> str:
    """Log a tool invocation as an immutable action record for an agent.

    Args:
        agent_id: UUID of the agent that invoked the tool.
        tool_name: Name of the tool that was called.
        input_params: Dict of input parameters passed to the tool.
        output_result: Dict of the tool's output or return value.
        status: Outcome — 'success', 'error', or 'timeout'.
        duration_ms: Execution time in milliseconds (optional).
        session_id: UUID of the session this action belongs to (optional).

    Returns:
        JSON with the created action record including its assigned ID.
    """
    body: dict[str, Any] = {
        "tool_name": tool_name,
        "input_params": input_params,
        "output_result": output_result,
        "status": status,
    }
    if duration_ms is not None:
        body["duration_ms"] = duration_ms
    if session_id is not None:
        body["session_id"] = session_id
    with _http() as c:
        data = _check(c.post(f"/v1/agents/{agent_id}/actions", json=body))
    return json.dumps(data)


@mcp.tool()
@auto_log
def action_list(
    agent_id: str,
    tool: str | None = None,
    status: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> str:
    """List recent actions for an agent with optional filters.

    Args:
        agent_id: UUID of the agent.
        tool: Filter by tool name (optional).
        status: Filter by outcome — 'success', 'error', or 'timeout' (optional).
        limit: Max number of results (1–500, default 50).
        cursor: Pagination cursor from a previous response (optional).

    Returns:
        JSON with an items list and next_cursor for pagination.
    """
    params: dict[str, Any] = {"limit": limit}
    if tool:
        params["tool"] = tool
    if status:
        params["status"] = status
    if cursor:
        params["cursor"] = cursor
    with _http() as c:
        data = _check(c.get(f"/v1/agents/{agent_id}/actions", params=params))
    return json.dumps(data)


# ---------------------------------------------------------------------------
# Context / blackboard
# ---------------------------------------------------------------------------


@mcp.tool()
@auto_log
def context_write(
    namespace: str,
    key: str,
    value: Any,
    agent_id: str | None = None,
) -> str:
    """Write a value to the shared context blackboard.

    The blackboard is a multi-agent coordination store. Any agent in the same
    tenant can read values written here, enabling inter-agent communication.

    Args:
        namespace: Logical grouping for related keys (e.g., 'project', 'pipeline').
        key: Key name within the namespace.
        value: Any JSON-serialisable value to store.
        agent_id: UUID of the calling agent (optional; enables status tracking and logging).

    Returns:
        JSON with the stored entry including version number.
    """
    with _http() as c:
        data = _check(c.put(
            f"/v1/context/{namespace}/{key}",
            json={"value": value},
        ))
    return json.dumps(data)


@mcp.tool()
@auto_log
def context_read(
    namespace: str,
    key: str,
    agent_id: str | None = None,
) -> str:
    """Read a value from the shared context blackboard.

    Args:
        namespace: Logical grouping for the key.
        key: Key name within the namespace.
        agent_id: UUID of the calling agent (optional; enables status tracking and logging).

    Returns:
        JSON with the stored value, version, and metadata.
        Raises an error if the key does not exist (404).
    """
    with _http() as c:
        data = _check(c.get(f"/v1/context/{namespace}/{key}"))
    return json.dumps(data)


# ---------------------------------------------------------------------------
# Agent status
# ---------------------------------------------------------------------------


@mcp.tool()
@auto_log
def agent_status(agent_id: str) -> str:
    """Get the current runtime status of an agent.

    Served from Redis cache (TTL 60 s) when available; falls back to PostgreSQL.

    Args:
        agent_id: UUID of the agent to query.

    Returns:
        JSON with status ('idle'/'working'/'error'), current_session_id, and updated_at.
    """
    with _http() as c:
        data = _check(c.get(f"/v1/agents/{agent_id}/status"))
    return json.dumps(data)


@mcp.tool()
@auto_log
def agent_set_status(
    agent_id: str,
    status: str,
    session_id: str | None = None,
) -> str:
    """Update the runtime status of an agent.

    Args:
        agent_id: UUID of the agent to update.
        status: New status — 'idle', 'working', or 'error'.
        session_id: UUID of an associated session (optional, used with 'working').

    Returns:
        JSON with the updated status record.
    """
    body: dict[str, Any] = {"status": status}
    if session_id:
        body["session_id"] = session_id
    with _http() as c:
        data = _check(c.patch(f"/v1/agents/{agent_id}/status", json=body))
    return json.dumps(data)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport=_TRANSPORT)
