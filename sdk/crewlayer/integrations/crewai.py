"""CrewAI integration for the CrewLayer SDK.

Provides two adapters:

- ``CrewLayerMemoryProvider`` — CrewAI ``Storage``-compatible memory backed by CrewLayer
- ``CrewLayerTaskLogger``     — task callback that logs each task completion as a CrewLayer action

Install::

    pip install crewlayer[crewai]

Usage::

    from crewlayer import CrewLayerClient
    from crewlayer.integrations.crewai import (
        CrewLayerMemoryProvider,
        CrewLayerTaskLogger,
    )
    from crewai import Agent, Task, Crew

    client = CrewLayerClient(api_key="crwl_...")

    memory_provider = CrewLayerMemoryProvider(client=client, agent_id="agent-uuid")
    task_logger = CrewLayerTaskLogger(client=client, agent_id="agent-uuid")

    task = Task(description="Analyze sales data", callback=task_logger)
    crew = Crew(agents=[...], tasks=[task], memory=True)
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Optional CrewAI imports — graceful fallback when not installed
# ---------------------------------------------------------------------------

try:
    from crewai.memory.storage.interface import Storage as _CrewAIStorage  # type: ignore[import]
    _CREWAI = True
except ImportError:
    try:
        from crewai.memory.storage.base import BaseMemoryStorage as _CrewAIStorage  # type: ignore[import, no-redef]
        _CREWAI = True
    except ImportError:
        _CREWAI = False
        _CrewAIStorage = object  # type: ignore[assignment, misc]


# ---------------------------------------------------------------------------
# CrewLayerMemoryProvider
# ---------------------------------------------------------------------------


class CrewLayerMemoryProvider(_CrewAIStorage):  # type: ignore[misc]
    """CrewAI-compatible ``Storage`` provider backed by CrewLayer.

    Implements the minimal CrewAI storage interface (``save`` / ``search`` /
    ``reset``) so it can be passed as the ``storage`` argument to any
    CrewAI memory class (``LongTermMemory``, ``ShortTermMemory``, etc.).

    Args:
        client:         A ``CrewLayerClient`` (sync) instance.
        agent_id:       Target agent UUID.
        session_id:     Session used for short-term memory writes (default ``"default"``).
        recall_limit:   Default number of results returned by ``search``
                        when no ``limit`` override is provided (default ``5``).
        min_similarity: Minimum cosine-similarity score for recall
                        (default ``0.35``).

    Example::

        from crewai.memory import LongTermMemory
        from crewlayer.integrations.crewai import CrewLayerMemoryProvider

        ltm = LongTermMemory(
            storage=CrewLayerMemoryProvider(client=client, agent_id="abc")
        )
    """

    def __init__(
        self,
        *,
        client: Any,
        agent_id: str,
        session_id: str = "default",
        recall_limit: int = 5,
        min_similarity: float = 0.35,
    ) -> None:
        super().__init__()
        # Bypass potential Pydantic __setattr__ if CrewAI uses Pydantic models
        self.__dict__.update({
            "_client": client,
            "_agent_id": agent_id,
            "_session_id": session_id,
            "_recall_limit": recall_limit,
            "_min_similarity": min_similarity,
        })

    # ------------------------------------------------------------------
    # CrewAI Storage interface
    # ------------------------------------------------------------------

    def save(
        self,
        value: Any,
        metadata: dict | None = None,
        agent: Any = None,
    ) -> None:
        """Persist a memory value to CrewLayer short-term memory."""
        self._client.memory.append(
            self._agent_id,
            role="assistant",
            content=str(value),
            session_id=self._session_id,
            metadata=metadata or {},
        )

    def search(
        self,
        query: str,
        *,
        limit: int | None = None,
        score_threshold: float | None = None,
    ) -> list[dict]:
        """Return memories semantically similar to *query*.

        Returns a list of dicts compatible with CrewAI's expected format::

            [{"id": ..., "memory": ..., "score": ..., "metadata": {...}}]
        """
        result = self._client.memory.recall(
            self._agent_id,
            query,
            limit=limit if limit is not None else self._recall_limit,
            min_similarity=score_threshold if score_threshold is not None else self._min_similarity,
        )
        return [
            {
                "id": item.id,
                "memory": item.content,
                "score": item.similarity or 0.0,
                "metadata": {
                    "importance": item.importance,
                    "tags": item.tags,
                },
            }
            for item in result.results
        ]

    def reset(self) -> None:
        """No-op — use a fresh ``session_id`` or rely on TTL-based eviction."""


# ---------------------------------------------------------------------------
# CrewLayerTaskLogger
# ---------------------------------------------------------------------------


class CrewLayerTaskLogger:
    """Callable CrewAI task callback that logs completions as CrewLayer actions.

    Pass an instance as ``callback=`` on any CrewAI ``Task``.  Each time the
    task finishes, the result is recorded as an action entry (status=success,
    tool_name=task description) so it appears in the agent's action history
    and can trigger alert rules.

    Args:
        client:     A ``CrewLayerClient`` (sync) instance.
        agent_id:   Target agent UUID.
        session_id: Optional session to associate the action with.

    Example::

        logger = CrewLayerTaskLogger(client=client, agent_id="agent-uuid")
        task = Task(description="Summarize customer feedback", callback=logger)
    """

    def __init__(
        self,
        *,
        client: Any,
        agent_id: str,
        session_id: str | None = None,
    ) -> None:
        self._client = client
        self._agent_id = agent_id
        self._session_id = session_id

    def __call__(self, task_output: Any) -> Any:
        """Log a completed task and return ``task_output`` unchanged."""
        # Prefer task name; fall back to description; truncate if needed
        tool_name = (
            getattr(task_output, "name", None)
            or getattr(task_output, "description", None)
            or "crewai_task"
        )
        if isinstance(tool_name, str) and len(tool_name) > 100:
            tool_name = tool_name[:100]

        raw_output = getattr(task_output, "raw", None) or str(task_output)

        try:
            self._client.actions.log(
                self._agent_id,
                tool_name=tool_name,
                input_params={},
                output_result={"output": str(raw_output)},
                status="success",
                session_id=self._session_id,
            )
        except Exception:
            # Never block task execution if logging fails
            pass

        return task_output
