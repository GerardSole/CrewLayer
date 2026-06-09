"""Memory resource clients — sync and async."""
from __future__ import annotations

from typing import Any

from crewlayer._http import AsyncTransport, SyncTransport
from crewlayer._types import (
    ExtractResult,
    MemoryItem,
    MemoryPage,
    RecallResult,
    ShortMemory,
)


class MemoryClient:
    """Synchronous memory operations."""

    def __init__(self, http: SyncTransport) -> None:
        self._http = http

    def append(
        self,
        agent_id: str,
        role: str,
        content: str,
        *,
        session_id: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> ShortMemory:
        """Append a message to the agent's short-term session memory."""
        data = self._http.request(
            "POST",
            f"/v1/agents/{agent_id}/memory/messages",
            params={"session_id": session_id},
            json={"role": role, "content": content, "metadata": metadata or {}},
        )
        return ShortMemory._from(data)

    def messages(
        self,
        agent_id: str,
        *,
        session_id: str = "default",
        limit: int = 50,
    ) -> ShortMemory:
        """Retrieve recent messages from the agent's session memory."""
        data = self._http.request(
            "GET",
            f"/v1/agents/{agent_id}/memory/messages",
            params={"session_id": session_id, "limit": limit},
        )
        return ShortMemory._from(data)

    def recall(
        self,
        agent_id: str,
        query: str,
        *,
        limit: int = 10,
        min_similarity: float = 0.0,
    ) -> RecallResult:
        """Semantic search over long-term memories using the query text."""
        data = self._http.request(
            "POST",
            f"/v1/agents/{agent_id}/memory/recall",
            json={"query": query, "limit": limit, "min_similarity": min_similarity},
        )
        return RecallResult._from(data)

    def extract(
        self,
        agent_id: str,
        conversation: str,
        *,
        session_id: str | None = None,
    ) -> ExtractResult:
        """Extract facts from a conversation with Claude and persist as long-term memories."""
        data = self._http.request(
            "POST",
            f"/v1/agents/{agent_id}/memory/extract",
            json={"conversation": conversation, "session_id": session_id},
        )
        return ExtractResult._from(data)

    def list(
        self,
        agent_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> MemoryPage:
        """List all long-term memories for an agent, paginated."""
        data = self._http.request(
            "GET",
            f"/v1/agents/{agent_id}/memory",
            params={"page": page, "page_size": page_size},
        )
        return MemoryPage._from(data)

    def delete(self, agent_id: str, memory_id: str) -> None:
        """Soft-delete a long-term memory record."""
        self._http.request("DELETE", f"/v1/agents/{agent_id}/memory/{memory_id}")


class AsyncMemoryClient:
    """Asynchronous memory operations."""

    def __init__(self, http: AsyncTransport) -> None:
        self._http = http

    async def append(
        self,
        agent_id: str,
        role: str,
        content: str,
        *,
        session_id: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> ShortMemory:
        """Append a message to the agent's short-term session memory."""
        data = await self._http.request(
            "POST",
            f"/v1/agents/{agent_id}/memory/messages",
            params={"session_id": session_id},
            json={"role": role, "content": content, "metadata": metadata or {}},
        )
        return ShortMemory._from(data)

    async def messages(
        self,
        agent_id: str,
        *,
        session_id: str = "default",
        limit: int = 50,
    ) -> ShortMemory:
        """Retrieve recent messages from the agent's session memory."""
        data = await self._http.request(
            "GET",
            f"/v1/agents/{agent_id}/memory/messages",
            params={"session_id": session_id, "limit": limit},
        )
        return ShortMemory._from(data)

    async def recall(
        self,
        agent_id: str,
        query: str,
        *,
        limit: int = 10,
        min_similarity: float = 0.0,
    ) -> RecallResult:
        """Semantic search over long-term memories using the query text."""
        data = await self._http.request(
            "POST",
            f"/v1/agents/{agent_id}/memory/recall",
            json={"query": query, "limit": limit, "min_similarity": min_similarity},
        )
        return RecallResult._from(data)

    async def extract(
        self,
        agent_id: str,
        conversation: str,
        *,
        session_id: str | None = None,
    ) -> ExtractResult:
        """Extract facts from a conversation with Claude and persist as long-term memories."""
        data = await self._http.request(
            "POST",
            f"/v1/agents/{agent_id}/memory/extract",
            json={"conversation": conversation, "session_id": session_id},
        )
        return ExtractResult._from(data)

    async def list(
        self,
        agent_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> MemoryPage:
        """List all long-term memories for an agent, paginated."""
        data = await self._http.request(
            "GET",
            f"/v1/agents/{agent_id}/memory",
            params={"page": page, "page_size": page_size},
        )
        return MemoryPage._from(data)

    async def delete(self, agent_id: str, memory_id: str) -> None:
        """Soft-delete a long-term memory record."""
        await self._http.request("DELETE", f"/v1/agents/{agent_id}/memory/{memory_id}")
