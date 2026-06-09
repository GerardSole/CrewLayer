"""Prometheus /metrics endpoint with access control.

Access is granted when ANY of these conditions holds:
  1. The request originates from localhost (127.0.0.1 / ::1).
  2. The request carries the correct X-Metrics-Token header.
  3. The request carries Authorization: Bearer <METRICS_TOKEN>.

Condition 3 lets Prometheus scrape via its standard `authorization` block
without extra plugin support.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from prometheus_client import REGISTRY, generate_latest

from crewlayer.core.config import settings

router = APIRouter()

_LOCAL_HOSTS = frozenset(("127.0.0.1", "::1"))


def _authorized(request: Request) -> bool:
    client_host = request.client.host if request.client else ""
    if client_host in _LOCAL_HOSTS:
        return True
    token = settings.METRICS_TOKEN
    if not token:
        return False
    if request.headers.get("X-Metrics-Token") == token:
        return True
    auth = request.headers.get("Authorization", "")
    return auth == f"Bearer {token}"


@router.get("/metrics", include_in_schema=False)
async def metrics_endpoint(request: Request) -> Response:
    """Prometheus metrics — localhost or token-authenticated only."""
    if not _authorized(request):
        raise HTTPException(status_code=403, detail="Forbidden")
    return Response(
        content=generate_latest(REGISTRY),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
