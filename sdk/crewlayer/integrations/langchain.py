"""LangChain integration for the CrewLayer SDK.

Provides three adapters:

- ``AgentLayerMemory``       — BaseChatMemory backed by CrewLayer short-term memory
- ``AgentLayerVectorStore``  — VectorStore backed by CrewLayer semantic recall
- ``AgentLayerCallbackHandler`` — logs every tool call as a CrewLayer action

Install::

    pip install crewlayer[langchain]

Usage::

    from crewlayer import CrewLayerClient
    from crewlayer.integrations.langchain import (
        AgentLayerMemory,
        AgentLayerVectorStore,
        AgentLayerCallbackHandler,
    )

    client = CrewLayerClient(api_key="crwl_...")

    memory = AgentLayerMemory(client=client, agent_id="agent-uuid")
    handler = AgentLayerCallbackHandler(client=client, agent_id="agent-uuid")
    chain = ConversationChain(llm=llm, memory=memory, callbacks=[handler])

    store = AgentLayerVectorStore(client=client, agent_id="agent-uuid")
    docs = store.similarity_search("user preferences", k=5)
"""
from __future__ import annotations

import time
from typing import Any, Sequence

# ---------------------------------------------------------------------------
# Optional LangChain imports — graceful fallback when not installed
# ---------------------------------------------------------------------------

try:
    from langchain_core.callbacks import BaseCallbackHandler as _LCCallbackHandler
    from langchain_core.documents import Document as _LCDocument
    from langchain_core.memory import BaseMemory as _LCBaseMemory
    from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
    from langchain_core.vectorstores import VectorStore as _LCVectorStore

    _LANGCHAIN = True
except ImportError:
    _LANGCHAIN = False
    _LCBaseMemory = object  # type: ignore[assignment, misc]
    _LCVectorStore = object  # type: ignore[assignment, misc]
    _LCCallbackHandler = object  # type: ignore[assignment, misc]

    class HumanMessage:  # type: ignore[no-redef]
        """Stub — requires langchain-core."""
        def __init__(self, content: str) -> None:
            self.content = content

    class AIMessage:  # type: ignore[no-redef]
        """Stub — requires langchain-core."""
        def __init__(self, content: str) -> None:
            self.content = content

    class BaseMessage:  # type: ignore[no-redef]
        content: str

    class _LCDocument:  # type: ignore[no-redef]
        def __init__(self, page_content: str, metadata: dict | None = None) -> None:
            self.page_content = page_content
            self.metadata = metadata or {}


# ---------------------------------------------------------------------------
# AgentLayerMemory
# ---------------------------------------------------------------------------


class AgentLayerMemory(_LCBaseMemory):  # type: ignore[misc]
    """LangChain ``BaseMemory`` implementation backed by CrewLayer short-term memory.

    Messages are stored in CrewLayer's Redis-backed session store and
    rehydrated on every chain call via ``load_memory_variables``.

    Args:
        client:          A ``CrewLayerClient`` (sync) instance.
        agent_id:        Target agent UUID.
        session_id:      Session key used for short-term memory (default ``"default"``).
        memory_key:      The key injected into the prompt template (default ``"history"``).
        return_messages: If ``True`` (default) return ``HumanMessage``/``AIMessage``
                         objects; otherwise return a plain string transcript.
        input_key:       Override which input key is treated as the human turn.
        output_key:      Override which output key is treated as the AI turn.
    """

    def __init__(
        self,
        *,
        client: Any,
        agent_id: str,
        session_id: str = "default",
        memory_key: str = "history",
        return_messages: bool = True,
        input_key: str | None = None,
        output_key: str | None = None,
    ) -> None:
        super().__init__()
        # Use __dict__ directly to bypass Pydantic's __setattr__ when
        # langchain-core's BaseMemory is a Pydantic model.
        self.__dict__.update({
            "_client": client,
            "_agent_id": agent_id,
            "_session_id": session_id,
            "_memory_key": memory_key,
            "_return_messages": return_messages,
            "_input_key": input_key,
            "_output_key": output_key,
        })

    # ------------------------------------------------------------------
    # BaseMemory interface
    # ------------------------------------------------------------------

    @property
    def memory_variables(self) -> list[str]:
        return [self._memory_key]

    def load_memory_variables(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Load session messages from CrewLayer and return them as the memory variable."""
        sm = self._client.memory.messages(
            self._agent_id, session_id=self._session_id
        )
        if self._return_messages:
            messages: list[Any] = []
            for m in sm.messages:
                if m.role in ("user", "human"):
                    messages.append(HumanMessage(content=m.content))
                else:
                    messages.append(AIMessage(content=m.content))
            return {self._memory_key: messages}

        lines = [f"{m.role}: {m.content}" for m in sm.messages]
        return {self._memory_key: "\n".join(lines)}

    def save_context(
        self, inputs: dict[str, Any], outputs: dict[str, str]
    ) -> None:
        """Append the latest human/AI turn to CrewLayer short-term memory."""
        input_key = self._input_key or next(iter(inputs), None)
        output_key = self._output_key or next(iter(outputs), None)

        if input_key and input_key in inputs:
            self._client.memory.append(
                self._agent_id,
                "user",
                str(inputs[input_key]),
                session_id=self._session_id,
            )
        if output_key and output_key in outputs:
            self._client.memory.append(
                self._agent_id,
                "assistant",
                str(outputs[output_key]),
                session_id=self._session_id,
            )

    def clear(self) -> None:
        """No-op — use a fresh ``session_id`` to start a new conversation."""


# ---------------------------------------------------------------------------
# AgentLayerVectorStore
# ---------------------------------------------------------------------------


class AgentLayerVectorStore(_LCVectorStore):  # type: ignore[misc]
    """LangChain ``VectorStore`` backed by CrewLayer's pgvector semantic recall.

    ``similarity_search`` maps directly to ``client.memory.recall`` — queries
    are embedded and scored by cosine similarity on the server.
    ``add_texts`` uses the memory-extract endpoint so that Claude processes
    and embeds each text as a long-term memory.

    Args:
        client:         A ``CrewLayerClient`` (sync) instance.
        agent_id:       Target agent UUID.
        k:              Default number of results (default ``4``).
        min_similarity: Minimum cosine similarity threshold (default ``0.0``).
    """

    def __init__(
        self,
        *,
        client: Any,
        agent_id: str,
        k: int = 4,
        min_similarity: float = 0.0,
    ) -> None:
        super().__init__()
        self.__dict__.update({
            "_client": client,
            "_agent_id": agent_id,
            "_k": k,
            "_min_similarity": min_similarity,
        })

    # ------------------------------------------------------------------
    # VectorStore interface
    # ------------------------------------------------------------------

    def add_texts(
        self,
        texts: Sequence[str],
        metadatas: list[dict] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        """Persist texts to CrewLayer as long-term memories via extraction."""
        ids: list[str] = []
        for text in texts:
            result = self._client.memory.extract(
                self._agent_id,
                conversation=f"Remember the following:\n{text}",
            )
            ids.extend(result.memory_ids)
        return ids

    def similarity_search(
        self,
        query: str,
        k: int | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        """Return the top-k memories most semantically similar to *query*."""
        limit = k if k is not None else self._k
        results = self._client.memory.recall(
            self._agent_id,
            query,
            limit=limit,
            min_similarity=self._min_similarity,
        )
        return [_to_document(item) for item in results.results]

    def similarity_search_with_score(
        self,
        query: str,
        k: int | None = None,
        **kwargs: Any,
    ) -> list[tuple[Any, float]]:
        """Return ``(Document, similarity_score)`` pairs."""
        limit = k if k is not None else self._k
        results = self._client.memory.recall(
            self._agent_id,
            query,
            limit=limit,
            min_similarity=self._min_similarity,
        )
        return [(_to_document(item), item.similarity or 0.0) for item in results.results]

    @classmethod
    def from_texts(
        cls,
        texts: list[str],
        embedding: Any,
        metadatas: list[dict] | None = None,
        *,
        client: Any,
        agent_id: str,
        **kwargs: Any,
    ) -> "AgentLayerVectorStore":
        """Factory: create a store, add *texts*, and return the instance."""
        store = cls(client=client, agent_id=agent_id, **kwargs)
        store.add_texts(texts, metadatas=metadatas)
        return store


def _to_document(item: Any) -> Any:
    return _LCDocument(
        page_content=item.content,
        metadata={
            "memory_id": item.id,
            "importance": item.importance,
            "tags": item.tags,
            "similarity": item.similarity,
        },
    )


# ---------------------------------------------------------------------------
# AgentLayerCallbackHandler
# ---------------------------------------------------------------------------


class AgentLayerCallbackHandler(_LCCallbackHandler):  # type: ignore[misc]
    """LangChain ``BaseCallbackHandler`` that logs tool calls to CrewLayer actions.

    Attach to any chain or agent executor to automatically record every tool
    invocation — name, input, output, and wall-clock duration — as an
    immutable action entry in CrewLayer.

    Args:
        client:     A ``CrewLayerClient`` (sync) instance.
        agent_id:   Target agent UUID.
        session_id: Optional session to associate actions with.

    Usage::

        handler = AgentLayerCallbackHandler(client=client, agent_id="agent-uuid")
        agent_executor.invoke({"input": "..."}, config={"callbacks": [handler]})
    """

    def __init__(
        self,
        *,
        client: Any,
        agent_id: str,
        session_id: str | None = None,
    ) -> None:
        super().__init__()
        self.__dict__.update({
            "_client": client,
            "_agent_id": agent_id,
            "_session_id": session_id,
            "_start_times": {},   # run_id → monotonic start
            "_tool_names": {},    # run_id → tool name
            "_tool_inputs": {},   # run_id → input string
        })

    # ------------------------------------------------------------------
    # BaseCallbackHandler interface
    # ------------------------------------------------------------------

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Record start time and tool name keyed by run_id."""
        if run_id is not None:
            key = str(run_id)
            self._start_times[key] = time.monotonic()
            name = (serialized or {}).get("name") or kwargs.get("name") or "tool"
            self._tool_names[key] = str(name)
            self._tool_inputs[key] = input_str

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Log a successful tool call as a CrewLayer action."""
        key = str(run_id) if run_id is not None else ""
        tool_name = self._tool_names.pop(key, None) or kwargs.get("name") or "tool"
        input_str = self._tool_inputs.pop(key, "")
        duration_ms = self._pop_duration(run_id)

        self._client.actions.log(
            self._agent_id,
            tool_name=tool_name,
            input_params={"input": input_str},
            output_result={"output": str(output)},
            status="success",
            session_id=self._session_id,
            duration_ms=duration_ms,
        )

    def on_tool_error(
        self,
        error: Any,
        *,
        run_id: Any = None,
        **kwargs: Any,
    ) -> None:
        """Log a failed tool call as a CrewLayer action with status=error."""
        key = str(run_id) if run_id is not None else ""
        tool_name = self._tool_names.pop(key, None) or kwargs.get("name") or "tool"
        input_str = self._tool_inputs.pop(key, "")
        duration_ms = self._pop_duration(run_id)

        self._client.actions.log(
            self._agent_id,
            tool_name=tool_name,
            input_params={"input": input_str},
            output_result={},
            status="error",
            error_msg=str(error),
            session_id=self._session_id,
            duration_ms=duration_ms,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _pop_duration(self, run_id: Any) -> int | None:
        if run_id is None:
            return None
        start = self._start_times.pop(str(run_id), None)
        if start is None:
            return None
        return max(0, int((time.monotonic() - start) * 1000))
