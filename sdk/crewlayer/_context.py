"""Context (blackboard) resource clients — sync and async."""
from __future__ import annotations

from typing import Any

from crewlayer._http import AsyncTransport, SyncTransport
from crewlayer._types import ContextEntry, ContextNamespace


class ContextClient:
    """Synchronous shared blackboard operations."""

    def __init__(self, http: SyncTransport) -> None:
        self._http = http

    def write(
        self,
        namespace: str,
        key: str,
        value: dict[str, Any],
        *,
        written_by: str | None = None,
        expires_at: str | None = None,
        expected_version: int | None = None,
    ) -> ContextEntry:
        """Write or overwrite a context entry.

        Pass expected_version to enable optimistic locking:
        - Use 0 to assert the key must not yet exist.
        - Use the version you last read to prevent clobbering concurrent writes.
        Raises ConflictError on mismatch.
        """
        data = self._http.request(
            "PUT",
            f"/v1/context/{namespace}/{key}",
            json={
                "value": value,
                "written_by": written_by,
                "expires_at": expires_at,
                "expected_version": expected_version,
            },
        )
        return ContextEntry._from(data)

    def read(self, namespace: str, key: str) -> ContextEntry:
        """Read a context entry. Raises NotFoundError if absent or expired."""
        data = self._http.request("GET", f"/v1/context/{namespace}/{key}")
        return ContextEntry._from(data)

    def list_namespace(self, namespace: str) -> ContextNamespace:
        """List all non-expired entries in a namespace, ordered by key."""
        data = self._http.request("GET", f"/v1/context/{namespace}")
        return ContextNamespace._from(data)

    def delete(self, namespace: str, key: str) -> None:
        """Delete a context entry. Raises NotFoundError if it does not exist."""
        self._http.request("DELETE", f"/v1/context/{namespace}/{key}")


class AsyncContextClient:
    """Asynchronous shared blackboard operations."""

    def __init__(self, http: AsyncTransport) -> None:
        self._http = http

    async def write(
        self,
        namespace: str,
        key: str,
        value: dict[str, Any],
        *,
        written_by: str | None = None,
        expires_at: str | None = None,
        expected_version: int | None = None,
    ) -> ContextEntry:
        """Write or overwrite a context entry.

        Pass expected_version to enable optimistic locking:
        - Use 0 to assert the key must not yet exist.
        - Use the version you last read to prevent clobbering concurrent writes.
        Raises ConflictError on mismatch.
        """
        data = await self._http.request(
            "PUT",
            f"/v1/context/{namespace}/{key}",
            json={
                "value": value,
                "written_by": written_by,
                "expires_at": expires_at,
                "expected_version": expected_version,
            },
        )
        return ContextEntry._from(data)

    async def read(self, namespace: str, key: str) -> ContextEntry:
        """Read a context entry. Raises NotFoundError if absent or expired."""
        data = await self._http.request("GET", f"/v1/context/{namespace}/{key}")
        return ContextEntry._from(data)

    async def list_namespace(self, namespace: str) -> ContextNamespace:
        """List all non-expired entries in a namespace, ordered by key."""
        data = await self._http.request("GET", f"/v1/context/{namespace}")
        return ContextNamespace._from(data)

    async def delete(self, namespace: str, key: str) -> None:
        """Delete a context entry. Raises NotFoundError if it does not exist."""
        await self._http.request("DELETE", f"/v1/context/{namespace}/{key}")
