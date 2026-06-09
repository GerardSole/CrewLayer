"""Top-level CrewLayer clients — sync and async."""
from __future__ import annotations

from typing import Any

from crewlayer._actions import ActionsClient, AsyncActionsClient
from crewlayer._context import AsyncContextClient, ContextClient
from crewlayer._http import AsyncTransport, SyncTransport
from crewlayer._memory import AsyncMemoryClient, MemoryClient

_DEFAULT_BASE_URL = "http://localhost:8000"


class CrewLayerClient:
    """Synchronous CrewLayer client.

    Usage::

        client = CrewLayerClient(api_key="crwl_...")
        client.memory.append(agent_id="...", role="user", content="Hello")
        result = client.memory.recall(agent_id="...", query="user preferences")
        client.close()

    As a context manager::

        with CrewLayerClient(api_key="crwl_...") as client:
            client.actions.log(agent_id="...", tool_name="send_email", ...)
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = _DEFAULT_BASE_URL,
    ) -> None:
        self._http = SyncTransport(api_key, base_url)
        self.memory = MemoryClient(self._http)
        self.actions = ActionsClient(self._http)
        self.context = ContextClient(self._http)

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._http.close()

    def __enter__(self) -> CrewLayerClient:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


class CrewLayerAsyncClient:
    """Asynchronous CrewLayer client.

    Usage::

        client = CrewLayerAsyncClient(api_key="crwl_...")
        await client.memory.append(agent_id="...", role="user", content="Hello")
        result = await client.memory.recall(agent_id="...", query="user preferences")
        await client.aclose()

    As an async context manager::

        async with CrewLayerAsyncClient(api_key="crwl_...") as client:
            await client.actions.log(agent_id="...", tool_name="send_email", ...)
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = _DEFAULT_BASE_URL,
    ) -> None:
        self._http = AsyncTransport(api_key, base_url)
        self.memory = AsyncMemoryClient(self._http)
        self.actions = AsyncActionsClient(self._http)
        self.context = AsyncContextClient(self._http)

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool."""
        await self._http.aclose()

    async def __aenter__(self) -> CrewLayerAsyncClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()
