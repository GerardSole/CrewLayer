"""Prompts resource clients — sync and async."""
from __future__ import annotations

from crewlayer._http import AsyncTransport, SyncTransport
from crewlayer._types import DiffLine, PromptDiff, PromptVersion, PromptVersionPage


class PromptsClient:
    """Synchronous prompt version control operations."""

    def __init__(self, http: SyncTransport) -> None:
        self._http = http

    def create(
        self,
        agent_id: str,
        content: str,
        *,
        description: str | None = None,
    ) -> PromptVersion:
        """Create a new prompt version (auto-increments the version number)."""
        data = self._http.request(
            "POST",
            f"/v1/agents/{agent_id}/prompts",
            json={"content": content, "description": description},
        )
        return PromptVersion._from(data)

    def list(self, agent_id: str) -> PromptVersionPage:
        """List all prompt versions for an agent, newest first."""
        data = self._http.request("GET", f"/v1/agents/{agent_id}/prompts")
        return PromptVersionPage._from(data)

    def get(self, agent_id: str, version_id: str) -> PromptVersion:
        """Retrieve a single prompt version by ID."""
        data = self._http.request("GET", f"/v1/agents/{agent_id}/prompts/{version_id}")
        return PromptVersion._from(data)

    def get_active(self, agent_id: str) -> PromptVersion:
        """Return the currently active prompt version."""
        data = self._http.request("GET", f"/v1/agents/{agent_id}/prompts/active")
        return PromptVersion._from(data)

    def activate(self, agent_id: str, version_id: str) -> PromptVersion:
        """Activate a specific version (deactivates any previously active one)."""
        data = self._http.request(
            "POST", f"/v1/agents/{agent_id}/prompts/{version_id}/activate"
        )
        return PromptVersion._from(data)

    def rollback(self, agent_id: str) -> PromptVersion:
        """Activate the version immediately before the currently active one."""
        data = self._http.request("POST", f"/v1/agents/{agent_id}/prompts/rollback")
        return PromptVersion._from(data)

    def diff(self, agent_id: str, version_id_a: str, version_id_b: str) -> PromptDiff:
        """Return a line-by-line diff between two versions."""
        data = self._http.request(
            "GET",
            f"/v1/agents/{agent_id}/prompts/diff",
            params={"a": version_id_a, "b": version_id_b},
        )
        return PromptDiff._from(data)


class AsyncPromptsClient:
    """Asynchronous prompt version control operations."""

    def __init__(self, http: AsyncTransport) -> None:
        self._http = http

    async def create(
        self,
        agent_id: str,
        content: str,
        *,
        description: str | None = None,
    ) -> PromptVersion:
        """Create a new prompt version (auto-increments the version number)."""
        data = await self._http.request(
            "POST",
            f"/v1/agents/{agent_id}/prompts",
            json={"content": content, "description": description},
        )
        return PromptVersion._from(data)

    async def list(self, agent_id: str) -> PromptVersionPage:
        """List all prompt versions for an agent, newest first."""
        data = await self._http.request("GET", f"/v1/agents/{agent_id}/prompts")
        return PromptVersionPage._from(data)

    async def get(self, agent_id: str, version_id: str) -> PromptVersion:
        """Retrieve a single prompt version by ID."""
        data = await self._http.request("GET", f"/v1/agents/{agent_id}/prompts/{version_id}")
        return PromptVersion._from(data)

    async def get_active(self, agent_id: str) -> PromptVersion:
        """Return the currently active prompt version."""
        data = await self._http.request("GET", f"/v1/agents/{agent_id}/prompts/active")
        return PromptVersion._from(data)

    async def activate(self, agent_id: str, version_id: str) -> PromptVersion:
        """Activate a specific version (deactivates any previously active one)."""
        data = await self._http.request(
            "POST", f"/v1/agents/{agent_id}/prompts/{version_id}/activate"
        )
        return PromptVersion._from(data)

    async def rollback(self, agent_id: str) -> PromptVersion:
        """Activate the version immediately before the currently active one."""
        data = await self._http.request(
            "POST", f"/v1/agents/{agent_id}/prompts/rollback"
        )
        return PromptVersion._from(data)

    async def diff(
        self, agent_id: str, version_id_a: str, version_id_b: str
    ) -> PromptDiff:
        """Return a line-by-line diff between two versions."""
        data = await self._http.request(
            "GET",
            f"/v1/agents/{agent_id}/prompts/diff",
            params={"a": version_id_a, "b": version_id_b},
        )
        return PromptDiff._from(data)
