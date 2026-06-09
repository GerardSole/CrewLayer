"""Immutable audit log middleware.

After every mutating request (POST/PUT/PATCH/DELETE) that passes authentication,
writes one AuditLog row with: who (key name + id), what (method + path + resource),
and the result (HTTP status code).

GET requests are never logged.  Unauthenticated requests (401) are never logged
because the API key is unknown.  403 and other errors on valid keys ARE logged.
"""

import asyncio
import contextlib
import re
import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from crewlayer.db.models import AuditLog
from crewlayer.db.session import AsyncSessionLocal

_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Ordered patterns: first match wins.  More specific paths must come before general ones.
_PATH_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^/v\d+/agents/[^/]+/memories"), "memory"),
    (re.compile(r"^/v\d+/agents/[^/]+/memory"), "memory"),
    (re.compile(r"^/v\d+/agents/[^/]+/actions"), "actions"),
    (re.compile(r"^/v\d+/agents/[^/]+/sessions"), "sessions"),
    (re.compile(r"^/v\d+/agents"), "agents"),
    (re.compile(r"^/v\d+/context"), "context"),
    (re.compile(r"^/v\d+/sessions"), "sessions"),
    (re.compile(r"^/v\d+/webhooks"), "webhooks"),
    (re.compile(r"^/v\d+/api-keys"), "api_keys"),
    (re.compile(r"^/v\d+/tenants"), "tenants"),
    (re.compile(r"^/v\d+/audit-log"), "audit_log"),
]

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def _classify_path(path: str) -> tuple[str | None, str | None]:
    resource_type: str | None = None
    for pattern, rtype in _PATH_PATTERNS:
        if pattern.match(path):
            resource_type = rtype
            break

    # First UUID in the path is the primary resource identifier
    m = _UUID_RE.search(path)
    resource_id = m.group(0) if m else None

    return resource_type, resource_id


async def _persist_entry(
    tenant_id: uuid.UUID,
    api_key_id: uuid.UUID,
    actor_key_name: str,
    method: str,
    path: str,
    status_code: int,
    ip_address: str | None,
) -> None:
    resource_type, resource_id = _classify_path(path)
    async with AsyncSessionLocal() as db:
        db.add(AuditLog(
            tenant_id=tenant_id,
            api_key_id=api_key_id,
            actor_key_name=actor_key_name,
            method=method,
            path=path,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
            status_code=status_code,
            timestamp=datetime.now(UTC),
        ))
        await db.commit()


class AuditLogMiddleware:
    """Pure ASGI middleware — does not buffer responses, compatible with SSE.

    Hooks into the send phase to capture the HTTP status code, then fires a
    background task to write the audit entry after the response is sent.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request = Request(scope, receive)

        if request.method not in _MUTATING_METHODS:
            await self._app(scope, receive, send)
            return

        status_code = 500

        async def _send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self._app(scope, receive, _send_wrapper)
        finally:
            audit_info = getattr(request.state, "audit_info", None)
            if audit_info is not None:
                ip = request.client.host if request.client else None
                with contextlib.suppress(RuntimeError):
                    asyncio.create_task(
                        _persist_entry(
                            tenant_id=audit_info.tenant_id,
                            api_key_id=audit_info.api_key_id,
                            actor_key_name=audit_info.actor_key_name,
                            method=request.method,
                            path=request.url.path,
                            status_code=status_code,
                            ip_address=ip,
                        )
                    )
