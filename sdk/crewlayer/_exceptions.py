"""Typed exception hierarchy for the CrewLayer SDK."""
from __future__ import annotations

from typing import Any


class CrewLayerError(Exception):
    """Base class for all CrewLayer SDK errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = response

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self!s}, status_code={self.status_code})"


class AuthError(CrewLayerError):
    """Raised on HTTP 401 / 403 — invalid or missing API key."""


class NotFoundError(CrewLayerError):
    """Raised on HTTP 404 — resource not found."""


class ConflictError(CrewLayerError):
    """Raised on HTTP 409 — optimistic locking version conflict."""


class RateLimitError(CrewLayerError):
    """Raised on HTTP 429 — request rate limit exceeded."""


class ServerError(CrewLayerError):
    """Raised on HTTP 5xx — transient server-side error (after retries exhausted)."""


_STATUS_MAP: dict[int, type[CrewLayerError]] = {
    401: AuthError,
    403: AuthError,
    404: NotFoundError,
    409: ConflictError,
    429: RateLimitError,
}


def raise_for_response(response: Any) -> None:  # response: httpx.Response
    """Raise the appropriate SDK exception if the response is not successful."""
    if response.is_success:
        return
    try:
        body: dict[str, Any] = response.json()
        detail: str = body.get("detail", response.text)
    except Exception:
        body = {}
        detail = response.text

    status = response.status_code
    if status >= 500:
        cls: type[CrewLayerError] = ServerError
    else:
        cls = _STATUS_MAP.get(status, CrewLayerError)

    raise cls(detail, status_code=status, response=body)
