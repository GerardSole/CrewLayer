"""LlamaIndex integration for the CrewLayer SDK.

Provides four adapters:

- ``CrewLayerMemoryBuffer``    — BaseMemory backed by CrewLayer short-term memory
- ``CrewLayerVectorIndex``     — index backed by CrewLayer semantic recall (pgvector)
- ``CrewLayerQueryEngine``     — query engine returned by ``index.as_query_engine()``,
                                  logs every query as a ``llamaindex.query`` action
- ``CrewLayerCallbackManager`` — BaseCallbackHandler that logs LLM calls and
                                  tool/function calls as CrewLayer actions

Install::

    pip install crewlayer[llamaindex]

Usage::

    from crewlayer import CrewLayerClient
    from crewlayer.integrations.llamaindex import (
        CrewLayerMemoryBuffer,
        CrewLayerVectorIndex,
        CrewLayerCallbackManager,
    )

    client = CrewLayerClient(api_key="crwl_...")

    # Chat memory
    memory = CrewLayerMemoryBuffer(client=client, agent_id="agent-uuid")

    # Vector index + query engine
    index = CrewLayerVectorIndex(client=client, agent_id="agent-uuid")
    index.insert(document)
    engine = index.as_query_engine()
    response = engine.query("¿qué recuerdas sobre el cliente?")
    print(response.response)

    # Callback handler (add to LlamaIndex's CallbackManager)
    from llama_index.core.callbacks import CallbackManager
    handler = CrewLayerCallbackManager(client=client, agent_id="agent-uuid")
    llm = OpenAI(callback_manager=CallbackManager([handler]))
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Optional LlamaIndex imports — graceful fallback when not installed
# ---------------------------------------------------------------------------

try:
    from llama_index.core.memory import BaseMemory as _LIBaseMemory  # type: ignore[import]
    from llama_index.core.llms import ChatMessage, MessageRole  # type: ignore[import]
    _LI_MEMORY = True
except ImportError:
    _LI_MEMORY = False
    _LIBaseMemory = object  # type: ignore[assignment, misc]

    class MessageRole:  # type: ignore[no-redef]
        USER = "user"
        ASSISTANT = "assistant"
        SYSTEM = "system"

    class ChatMessage:  # type: ignore[no-redef]
        """Stub — requires llama-index-core."""
        def __init__(self, role: Any = "user", content: str = "", **kwargs: Any) -> None:
            self.role = role
            self.content = content


try:
    from llama_index.core.callbacks.base_handler import (  # type: ignore[import]
        BaseCallbackHandler as _LIBaseCallbackHandler,
    )
    from llama_index.core.callbacks.schema import CBEventType  # type: ignore[import]
    _LI_CALLBACKS = True
except ImportError:
    _LI_CALLBACKS = False
    _LIBaseCallbackHandler = object  # type: ignore[assignment, misc]

    class CBEventType:  # type: ignore[no-redef]
        """Stub — requires llama-index-core."""
        LLM = "llm"
        FUNCTION_CALL = "function_call"
        AGENT_STEP = "agent_step"
        QUERY = "query"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Event names that are worth logging to CrewLayer (avoids noise from EMBEDDING etc.)
_LOGGED_EVENTS: frozenset[str] = frozenset({"llm", "function_call", "agent_step"})


def _role_str(role: Any) -> str:
    """Normalise a LlamaIndex MessageRole (enum or str) to a plain string."""
    s = str(role.value if hasattr(role, "value") else role)
    return "user" if s == "human" else s


def _event_name(event_type: Any) -> str:
    return str(event_type.value if hasattr(event_type, "value") else event_type)


@dataclass
class QueryResponse:
    """Lightweight response returned by ``CrewLayerQueryEngine.query()``.

    Compatible with direct use; also holds the raw ``source_nodes`` from
    CrewLayer so callers can inspect similarity scores without needing
    the full LlamaIndex response hierarchy.
    """

    response: str
    source_nodes: list[Any] = field(default_factory=list)

    def __str__(self) -> str:
        return self.response


# ---------------------------------------------------------------------------
# CrewLayerMemoryBuffer
# ---------------------------------------------------------------------------


class CrewLayerMemoryBuffer(_LIBaseMemory):  # type: ignore[misc]
    """LlamaIndex ``BaseMemory`` backed by CrewLayer short-term memory.

    Each ``put()`` call appends a message to the agent's Redis session store.
    ``get()`` fetches recent messages and converts them to ``ChatMessage`` objects.

    Args:
        client:     A ``CrewLayerClient`` (sync) instance.
        agent_id:   Target agent UUID.
        session_id: Session key (default ``"default"``).
        limit:      Max messages returned by ``get()`` (default ``50``).
    """

    def __init__(
        self,
        *,
        client: Any,
        agent_id: str,
        session_id: str = "default",
        limit: int = 50,
    ) -> None:
        # Use __dict__ directly to bypass Pydantic's __setattr__ when
        # llama_index's BaseMemory is a Pydantic model.
        try:
            super().__init__()
        except TypeError:
            pass
        self.__dict__.update({
            "_client": client,
            "_agent_id": agent_id,
            "_session_id": session_id,
            "_limit": limit,
        })

    # ------------------------------------------------------------------
    # BaseMemory interface
    # ------------------------------------------------------------------

    def get(self, input: str | None = None, **kwargs: Any) -> list[Any]:
        """Return recent messages as ``ChatMessage`` objects."""
        sm = self._client.memory.messages(
            self._agent_id,
            session_id=self._session_id,
            limit=self._limit,
        )
        return [
            ChatMessage(role=_role_str(m.role), content=m.content)
            for m in sm.messages
        ]

    def get_all(self) -> list[Any]:
        """Return all stored messages — delegates to ``get()``."""
        return self.get()

    def put(self, message: Any) -> None:
        """Append a single ``ChatMessage`` to CrewLayer short-term memory."""
        role = _role_str(getattr(message, "role", "user"))
        content = str(getattr(message, "content", ""))
        self._client.memory.append(
            self._agent_id,
            role,
            content,
            session_id=self._session_id,
        )

    def set(self, messages: list[Any]) -> None:
        """Overwrite history by appending each message in order."""
        for m in messages:
            self.put(m)

    def reset(self) -> None:
        """No-op — use a fresh ``session_id`` or rely on Redis TTL."""


# ---------------------------------------------------------------------------
# CrewLayerVectorIndex
# ---------------------------------------------------------------------------


class CrewLayerVectorIndex:
    """Vector index backed by CrewLayer semantic recall.

    ``insert()`` persists documents as long-term memories via the extract
    endpoint.  ``similarity_search()`` uses pgvector cosine similarity.
    ``as_query_engine()`` returns a :class:`CrewLayerQueryEngine` that logs
    every query as a ``llamaindex.query`` action.

    Args:
        client:           A ``CrewLayerClient`` (sync) instance.
        agent_id:         Target agent UUID.
        similarity_top_k: Default number of results (default ``4``).
        min_similarity:   Minimum cosine similarity threshold (default ``0.0``).
    """

    def __init__(
        self,
        *,
        client: Any,
        agent_id: str,
        similarity_top_k: int = 4,
        min_similarity: float = 0.0,
    ) -> None:
        self._client = client
        self._agent_id = agent_id
        self._similarity_top_k = similarity_top_k
        self._min_similarity = min_similarity

    def insert(self, document: Any) -> list[str]:
        """Persist a document as long-term memory via the extract endpoint.

        Accepts any object with a ``.text`` or ``.get_content()`` attribute,
        or anything ``str()``-able.

        Returns the list of new memory IDs.
        """
        text = (
            getattr(document, "text", None)
            or (
                document.get_content()
                if callable(getattr(document, "get_content", None))
                else None
            )
            or str(document)
        )
        result = self._client.memory.extract(
            self._agent_id,
            conversation=f"Remember the following:\n{text}",
        )
        return result.memory_ids

    def similarity_search(self, query: str, top_k: int | None = None) -> list[Any]:
        """Return the top-k memories most similar to *query*.

        Returns a list of ``MemoryItem`` objects (from ``_types.py``).
        """
        limit = top_k if top_k is not None else self._similarity_top_k
        result = self._client.memory.recall(
            self._agent_id,
            query,
            limit=limit,
            min_similarity=self._min_similarity,
        )
        return result.results

    def as_query_engine(
        self,
        *,
        session_id: str | None = None,
        similarity_top_k: int | None = None,
    ) -> "CrewLayerQueryEngine":
        """Return a :class:`CrewLayerQueryEngine` backed by this index."""
        return CrewLayerQueryEngine(
            index=self,
            session_id=session_id,
            similarity_top_k=similarity_top_k,
        )


# ---------------------------------------------------------------------------
# CrewLayerQueryEngine
# ---------------------------------------------------------------------------


class CrewLayerQueryEngine:
    """Query engine that retrieves from CrewLayer and logs each call as an action.

    Returned by :meth:`CrewLayerVectorIndex.as_query_engine`.  Can also be
    instantiated directly if you already have an index reference.

    Args:
        index:            A :class:`CrewLayerVectorIndex` instance.
        session_id:       Optional session to associate actions with.
        similarity_top_k: Override the index default ``similarity_top_k``.
    """

    def __init__(
        self,
        *,
        index: CrewLayerVectorIndex,
        session_id: str | None = None,
        similarity_top_k: int | None = None,
    ) -> None:
        self._index = index
        self._session_id = session_id
        self._similarity_top_k = similarity_top_k

    def query(self, query_str: str, **kwargs: Any) -> QueryResponse:
        """Retrieve memories for *query_str*, log the call, and return a response.

        The action is always logged with ``tool_name="llamaindex.query"``.
        The response text is the concatenation of the top result contents.
        ``source_nodes`` holds the raw ``MemoryItem`` list for further inspection.
        """
        start = time.monotonic()
        try:
            nodes = self._index.similarity_search(
                query_str,
                top_k=self._similarity_top_k,
            )
            duration_ms = max(0, int((time.monotonic() - start) * 1000))
            response_text = "\n\n".join(item.content for item in nodes) if nodes else ""
            self._index._client.actions.log(
                self._index._agent_id,
                tool_name="llamaindex.query",
                input_params={"query": query_str},
                output_result={
                    "results_count": len(nodes),
                    "response": response_text[:500],
                },
                status="success",
                session_id=self._session_id,
                duration_ms=duration_ms,
            )
            return QueryResponse(response=response_text, source_nodes=nodes)
        except Exception as exc:
            duration_ms = max(0, int((time.monotonic() - start) * 1000))
            self._index._client.actions.log(
                self._index._agent_id,
                tool_name="llamaindex.query",
                input_params={"query": query_str},
                output_result={},
                status="error",
                error_msg=str(exc),
                session_id=self._session_id,
                duration_ms=duration_ms,
            )
            raise


# ---------------------------------------------------------------------------
# CrewLayerCallbackManager
# ---------------------------------------------------------------------------


class CrewLayerCallbackManager(_LIBaseCallbackHandler):  # type: ignore[misc]
    """LlamaIndex ``BaseCallbackHandler`` that logs LLM and tool calls to CrewLayer.

    Add an instance of this class to LlamaIndex's ``CallbackManager`` to
    automatically record every LLM call, function call, and agent step as
    an immutable action entry in CrewLayer.

    Tracked event types: ``llm``, ``function_call``, ``agent_step``.

    Args:
        client:     A ``CrewLayerClient`` (sync) instance.
        agent_id:   Target agent UUID.
        session_id: Optional session to associate actions with.

    Usage::

        from llama_index.core.callbacks import CallbackManager
        handler = CrewLayerCallbackManager(client=client, agent_id="agent-uuid")
        callback_manager = CallbackManager([handler])
        llm = OpenAI(callback_manager=callback_manager)
    """

    def __init__(
        self,
        *,
        client: Any,
        agent_id: str,
        session_id: str | None = None,
    ) -> None:
        # BaseCallbackHandler (when installed) expects event ignore lists.
        try:
            super().__init__(event_starts_to_ignore=[], event_ends_to_ignore=[])
        except TypeError:
            try:
                super().__init__()
            except TypeError:
                pass
        self.__dict__.update({
            "_client": client,
            "_agent_id": agent_id,
            "_session_id": session_id,
            "_start_times": {},   # event_id → monotonic start
            "_start_payloads": {},  # event_id → payload dict at start
        })

    # ------------------------------------------------------------------
    # BaseCallbackHandler interface
    # ------------------------------------------------------------------

    def on_event_start(
        self,
        event_type: Any,
        payload: dict[str, Any] | None = None,
        event_id: str = "",
        parent_id: str = "",
        **kwargs: Any,
    ) -> str:
        """Record the start time for tracked events."""
        name = _event_name(event_type)
        if name in _LOGGED_EVENTS and event_id:
            self._start_times[event_id] = time.monotonic()
            self._start_payloads[event_id] = payload or {}
        return event_id

    def on_event_end(
        self,
        event_type: Any,
        payload: dict[str, Any] | None = None,
        event_id: str = "",
        **kwargs: Any,
    ) -> None:
        """Log the completed event as a CrewLayer action."""
        name = _event_name(event_type)
        if name not in _LOGGED_EVENTS:
            return

        payload = payload or {}
        duration_ms = self._pop_duration(event_id)
        tool_name = f"llamaindex.{name}"

        # Extract a concise output summary from the payload
        output = _extract_output(payload)
        input_info = _extract_input(self._start_payloads.pop(event_id, {}))

        try:
            self._client.actions.log(
                self._agent_id,
                tool_name=tool_name,
                input_params=input_info,
                output_result=output,
                status="success",
                session_id=self._session_id,
                duration_ms=duration_ms,
            )
        except Exception:
            pass  # Never block the LlamaIndex pipeline

    def start_trace(self, trace_id: str | None = None) -> None:
        """No-op — CrewLayer tracing is handled at the action level."""

    def end_trace(
        self,
        trace_id: str | None = None,
        trace_map: dict[str, Any] | None = None,
    ) -> None:
        """No-op."""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _pop_duration(self, event_id: str) -> int | None:
        start = self._start_times.pop(event_id, None)
        if start is None:
            return None
        return max(0, int((time.monotonic() - start) * 1000))


def _extract_output(payload: dict[str, Any]) -> dict[str, Any]:
    """Pull a loggable summary from a LlamaIndex event end payload."""
    out: dict[str, Any] = {}

    # LLM response
    response = payload.get("response")
    if response is not None:
        # CompletionResponse / ChatResponse both have .text or .message.content
        text = getattr(response, "text", None)
        if text is None:
            msg = getattr(response, "message", None)
            text = getattr(msg, "content", None) if msg is not None else None
        if text is not None:
            out["response"] = str(text)[:500]

    # Function call response
    fc_response = payload.get("function_call_response")
    if fc_response is not None:
        out["function_call_response"] = str(fc_response)[:500]

    # Token usage
    for key in ("num_input_tokens", "num_output_tokens", "model_name"):
        if key in payload:
            out[key] = payload[key]

    return out or {"raw": str(payload)[:200]}


def _extract_input(payload: dict[str, Any]) -> dict[str, Any]:
    """Pull a loggable summary from a LlamaIndex event start payload."""
    inp: dict[str, Any] = {}

    # LLM messages list
    messages = payload.get("messages")
    if messages:
        inp["message_count"] = len(messages)
        last = messages[-1]
        inp["last_message"] = str(
            getattr(last, "content", str(last))
        )[:300]

    # Function call info
    for key in ("function_call", "function_name", "model_name"):
        if key in payload:
            inp[key] = str(payload[key])[:200]

    return inp or {}
