"""Custom Prometheus metrics for CrewLayer.

Six Gauge metrics are declared here and refreshed every 60 s via a background
task (see main.py).  All queries are read-only and scoped to the metrics
collection interval — they never touch the request path.

Metric prefix: crewlayer_
"""
from __future__ import annotations

import logging
from contextlib import suppress

from prometheus_client import Gauge
from sqlalchemy import text

from crewlayer.db.session import AsyncSessionLocal

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gauge declarations — registered with the default REGISTRY on module import
# ---------------------------------------------------------------------------

memories_total = Gauge(
    "crewlayer_memories_total",
    "Total non-deleted memories per tenant",
    ["tenant_id"],
)

actions_total = Gauge(
    "crewlayer_actions_total",
    "Total logged actions per tenant, tool, and outcome",
    ["tenant_id", "tool_name", "status"],
)

active_sessions = Gauge(
    "crewlayer_active_sessions",
    "Number of currently active sessions per tenant",
    ["tenant_id"],
)

agents_by_status = Gauge(
    "crewlayer_agents_by_status",
    "Number of agents in each runtime status",
    ["status"],
)

memory_importance_avg = Gauge(
    "crewlayer_memory_importance_avg",
    "Average importance score of non-deleted memories per tenant",
    ["tenant_id"],
)

api_key_usage_total = Gauge(
    "crewlayer_api_key_usage_total",
    "Total authenticated API requests per tenant and key name (from audit log)",
    ["tenant_id", "key_name"],
)


# ---------------------------------------------------------------------------
# Refresh logic
# ---------------------------------------------------------------------------

async def collect_metrics() -> None:
    """Refresh all custom Gauges by querying PostgreSQL.

    Errors are suppressed so a temporary DB outage never crashes the process.
    Called every 60 s from the background loop in main.py.
    """
    with suppress(Exception):
        async with AsyncSessionLocal() as db:
            await _run_queries(db)
        _log.debug("crewlayer custom metrics refreshed")


async def _run_queries(db: object) -> None:  # db: AsyncSession — typed as object to avoid import cycle
    from sqlalchemy.ext.asyncio import AsyncSession  # local import; no cycle at runtime
    assert isinstance(db, AsyncSession)

    rows = (await db.execute(
        text(
            "SELECT tenant_id::text, COUNT(*) "
            "FROM memories WHERE deleted_at IS NULL "
            "GROUP BY tenant_id"
        )
    )).all()
    for tid, cnt in rows:
        memories_total.labels(tenant_id=tid).set(int(cnt))

    rows = (await db.execute(
        text(
            "SELECT tenant_id::text, tool_name, status::text, COUNT(*) "
            "FROM actions "
            "GROUP BY tenant_id, tool_name, status"
        )
    )).all()
    for tid, tool, st, cnt in rows:
        actions_total.labels(tenant_id=tid, tool_name=tool, status=st).set(int(cnt))

    rows = (await db.execute(
        text(
            "SELECT tenant_id::text, COUNT(*) "
            "FROM sessions WHERE status = 'active' "
            "GROUP BY tenant_id"
        )
    )).all()
    for tid, cnt in rows:
        active_sessions.labels(tenant_id=tid).set(int(cnt))

    rows = (await db.execute(
        text("SELECT status::text, COUNT(*) FROM agents GROUP BY status")
    )).all()
    for st, cnt in rows:
        agents_by_status.labels(status=st).set(int(cnt))

    rows = (await db.execute(
        text(
            "SELECT tenant_id::text, AVG(importance) "
            "FROM memories WHERE deleted_at IS NULL "
            "GROUP BY tenant_id"
        )
    )).all()
    for tid, avg in rows:
        memory_importance_avg.labels(tenant_id=tid).set(float(avg or 0.0))

    rows = (await db.execute(
        text(
            "SELECT tenant_id::text, actor_key_name, COUNT(*) "
            "FROM audit_log "
            "GROUP BY tenant_id, actor_key_name"
        )
    )).all()
    for tid, key_name, cnt in rows:
        api_key_usage_total.labels(tenant_id=tid, key_name=key_name).set(int(cnt))
