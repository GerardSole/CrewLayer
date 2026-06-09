"""HTTP transports with automatic retry on transient 5xx errors."""
from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from crewlayer._exceptions import raise_for_response

_RETRY_ON = frozenset({500, 502, 503, 504})
_MAX_RETRIES = 3


class SyncTransport:
    """Synchronous HTTP transport built on httpx.Client."""

    def __init__(self, api_key: str, base_url: str) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"X-API-Key": api_key},
            timeout=30.0,
        )

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Execute a request, retrying on 5xx with exponential backoff.

        Backoff: 1 s, 2 s, 4 s (2^attempt seconds, up to _MAX_RETRIES retries).
        Returns {} for 204 No Content responses.
        """
        response: httpx.Response | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = self._client.request(method, path, **kwargs)
            except httpx.TransportError:
                if attempt < _MAX_RETRIES:
                    time.sleep(2 ** attempt)
                    continue
                raise
            if response.status_code in _RETRY_ON and attempt < _MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue
            break

        assert response is not None
        raise_for_response(response)
        return {} if response.status_code == 204 else response.json()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SyncTransport:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


class AsyncTransport:
    """Asynchronous HTTP transport built on httpx.AsyncClient."""

    def __init__(self, api_key: str, base_url: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"X-API-Key": api_key},
            timeout=30.0,
        )

    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Execute a request, retrying on 5xx with exponential backoff (async sleep).

        Backoff: 1 s, 2 s, 4 s (2^attempt seconds, up to _MAX_RETRIES retries).
        Returns {} for 204 No Content responses.
        """
        response: httpx.Response | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = await self._client.request(method, path, **kwargs)
            except httpx.TransportError:
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise
            if response.status_code in _RETRY_ON and attempt < _MAX_RETRIES:
                await asyncio.sleep(2 ** attempt)
                continue
            break

        assert response is not None
        raise_for_response(response)
        return {} if response.status_code == 204 else response.json()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> AsyncTransport:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()
