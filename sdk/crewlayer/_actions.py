"""Actions resource clients — sync and async."""
from __future__ import annotations

from typing import Any

from crewlayer._http import AsyncTransport, SyncTransport
from crewlayer._types import ActionPage, ActionRecord, ActionStats


class ActionsClient:
    """Synchronous action log operations."""

    def __init__(self, http: SyncTransport) -> None:
        self._http = http

    def log(
        self,
        agent_id: str,
        tool_name: str,
        input_params: dict[str, Any],
        output_result: dict[str, Any],
        status: str,
        *,
        session_id: str | None = None,
        duration_ms: int | None = None,
        error_msg: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ActionRecord:
        """Record an immutable action entry for the agent."""
        data = self._http.request(
            "POST",
            f"/v1/agents/{agent_id}/actions",
            json={
                "tool_name": tool_name,
                "input_params": input_params,
                "output_result": output_result,
                "status": status,
                "session_id": session_id,
                "duration_ms": duration_ms,
                "error_msg": error_msg,
                "metadata": metadata or {},
            },
        )
        return ActionRecord._from(data)

    def get(self, agent_id: str, action_id: str) -> ActionRecord:
        """Retrieve a single action by ID."""
        data = self._http.request("GET", f"/v1/agents/{agent_id}/actions/{action_id}")
        return ActionRecord._from(data)

    def list(
        self,
        agent_id: str,
        *,
        tool: str | None = None,
        status: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> ActionPage:
        """List actions with optional filters. Paginated via cursor."""
        params: dict[str, Any] = {"limit": limit}
        if tool is not None:
            params["tool"] = tool
        if status is not None:
            params["status"] = status
        if since is not None:
            params["since"] = since
        if until is not None:
            params["until"] = until
        if cursor is not None:
            params["cursor"] = cursor
        data = self._http.request("GET", f"/v1/agents/{agent_id}/actions", params=params)
        return ActionPage._from(data)

    def stats(self, agent_id: str) -> ActionStats:
        """Aggregate statistics: totals, error rate, average duration, per-tool breakdown."""
        data = self._http.request("GET", f"/v1/agents/{agent_id}/actions/stats")
        return ActionStats._from(data)


class AsyncActionsClient:
    """Asynchronous action log operations."""

    def __init__(self, http: AsyncTransport) -> None:
        self._http = http

    async def log(
        self,
        agent_id: str,
        tool_name: str,
        input_params: dict[str, Any],
        output_result: dict[str, Any],
        status: str,
        *,
        session_id: str | None = None,
        duration_ms: int | None = None,
        error_msg: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ActionRecord:
        """Record an immutable action entry for the agent."""
        data = await self._http.request(
            "POST",
            f"/v1/agents/{agent_id}/actions",
            json={
                "tool_name": tool_name,
                "input_params": input_params,
                "output_result": output_result,
                "status": status,
                "session_id": session_id,
                "duration_ms": duration_ms,
                "error_msg": error_msg,
                "metadata": metadata or {},
            },
        )
        return ActionRecord._from(data)

    async def get(self, agent_id: str, action_id: str) -> ActionRecord:
        """Retrieve a single action by ID."""
        data = await self._http.request("GET", f"/v1/agents/{agent_id}/actions/{action_id}")
        return ActionRecord._from(data)

    async def list(
        self,
        agent_id: str,
        *,
        tool: str | None = None,
        status: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> ActionPage:
        """List actions with optional filters. Paginated via cursor."""
        params: dict[str, Any] = {"limit": limit}
        if tool is not None:
            params["tool"] = tool
        if status is not None:
            params["status"] = status
        if since is not None:
            params["since"] = since
        if until is not None:
            params["until"] = until
        if cursor is not None:
            params["cursor"] = cursor
        data = await self._http.request("GET", f"/v1/agents/{agent_id}/actions", params=params)
        return ActionPage._from(data)

    async def stats(self, agent_id: str) -> ActionStats:
        """Aggregate statistics: totals, error rate, average duration, per-tool breakdown."""
        data = await self._http.request("GET", f"/v1/agents/{agent_id}/actions/stats")
        return ActionStats._from(data)
