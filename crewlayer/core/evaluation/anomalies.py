"""Automatic anomaly detection for agent actions.

Called in background after every action commit. Creates Anomaly records
and fires webhooks for high-severity findings.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.db.models import (
    Action,
    ActionStatus,
    Anomaly,
    AnomalySeverityEnum,
    AnomalyTypeEnum,
    Evaluation,
)

_DEFAULT_MAX_OUTPUT_CHARS = 5_000
_DEFAULT_TOOL_OVERUSE_N = 5
_DEFAULT_HIGH_LATENCY_MS = 10_000
_DEFAULT_ERROR_SPIKE = 3
_LOW_SCORE_THRESHOLD = 2.0
_LOW_SCORE_WINDOW = 5


@dataclass
class _Detection:
    anomaly_type: AnomalyTypeEnum
    severity: AnomalySeverityEnum
    details: dict[str, Any]


def _agent_cfg(agent_config: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], agent_config.get("anomaly_detection", {}))


class AnomalyManager:

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    async def detect(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        action: Action,
        agent_config: dict[str, Any],
        redis: Redis,
    ) -> list[Anomaly]:
        """Run all detectors and persist any findings. Returns created anomaly rows."""
        cfg = _agent_cfg(agent_config)
        detections: list[_Detection] = []

        detections.extend(self._check_response_too_long(action, cfg))
        detections.extend(await self._check_tool_overuse(tenant_id, agent_id, action, cfg))
        detections.extend(self._check_high_latency(action, cfg))
        detections.extend(await self._check_error_spike(tenant_id, agent_id, action, redis, cfg))
        detections.extend(await self._check_low_score_streak(tenant_id, agent_id))

        created: list[Anomaly] = []
        for d in detections:
            row = Anomaly(
                tenant_id=tenant_id,
                agent_id=agent_id,
                action_id=action.id,
                anomaly_type=d.anomaly_type,
                severity=d.severity,
                details=d.details,
                resolved=False,
            )
            self._db.add(row)
            created.append(row)

        if created:
            await self._db.flush()

        return created

    def _check_response_too_long(
        self, action: Action, cfg: dict[str, Any]
    ) -> list[_Detection]:
        threshold = int(cfg.get("max_output_chars", _DEFAULT_MAX_OUTPUT_CHARS))
        output_str = json.dumps(action.output_result)
        length = len(output_str)
        if length > threshold:
            return [_Detection(
                anomaly_type=AnomalyTypeEnum.response_too_long,
                severity=AnomalySeverityEnum.medium,
                details={"output_chars": length, "threshold": threshold},
            )]
        return []

    async def _check_tool_overuse(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        action: Action,
        cfg: dict[str, Any],
    ) -> list[_Detection]:
        if not action.session_id:
            return []
        threshold = int(cfg.get("tool_overuse_n", _DEFAULT_TOOL_OVERUSE_N))
        result = await self._db.execute(
            select(func.count()).where(
                Action.tenant_id == tenant_id,
                Action.agent_id == agent_id,
                Action.session_id == action.session_id,
                Action.tool_name == action.tool_name,
            )
        )
        count = int(result.scalar() or 0)
        if count > threshold:
            return [_Detection(
                anomaly_type=AnomalyTypeEnum.tool_overuse,
                severity=AnomalySeverityEnum.medium,
                details={
                    "tool_name": action.tool_name,
                    "uses_in_session": count,
                    "threshold": threshold,
                },
            )]
        return []

    def _check_high_latency(
        self, action: Action, cfg: dict[str, Any]
    ) -> list[_Detection]:
        if action.duration_ms is None:
            return []
        threshold = int(cfg.get("high_latency_ms", _DEFAULT_HIGH_LATENCY_MS))
        if action.duration_ms > threshold:
            return [_Detection(
                anomaly_type=AnomalyTypeEnum.high_latency,
                severity=AnomalySeverityEnum.low
                if action.duration_ms < threshold * 2
                else AnomalySeverityEnum.high,
                details={"duration_ms": action.duration_ms, "threshold": threshold},
            )]
        return []

    async def _check_error_spike(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        action: Action,
        redis: Redis,
        cfg: dict[str, Any],
    ) -> list[_Detection]:
        if action.status not in (ActionStatus.error, ActionStatus.timeout):
            return []
        threshold = int(cfg.get("error_spike_n", _DEFAULT_ERROR_SPIKE))
        redis_key = f"alert:{tenant_id}:{agent_id}:consecutive_errors"
        count = int(await redis.get(redis_key) or 0)
        if count >= threshold:
            return [_Detection(
                anomaly_type=AnomalyTypeEnum.error_spike,
                severity=AnomalySeverityEnum.high,
                details={"consecutive_errors": count, "threshold": threshold},
            )]
        return []

    async def _check_low_score_streak(
        self, tenant_id: uuid.UUID, agent_id: uuid.UUID
    ) -> list[_Detection]:
        result = await self._db.execute(
            select(Evaluation.rating_score)
            .where(
                Evaluation.tenant_id == tenant_id,
                Evaluation.agent_id == agent_id,
                Evaluation.rating_score.is_not(None),
            )
            .order_by(Evaluation.created_at.desc())
            .limit(_LOW_SCORE_WINDOW)
        )
        scores = [row[0] for row in result.all()]
        if len(scores) == _LOW_SCORE_WINDOW and all(s < _LOW_SCORE_THRESHOLD for s in scores):
            return [_Detection(
                anomaly_type=AnomalyTypeEnum.low_score_streak,
                severity=AnomalySeverityEnum.high,
                details={
                    "window": _LOW_SCORE_WINDOW,
                    "scores": scores,
                    "threshold": _LOW_SCORE_THRESHOLD,
                },
            )]
        return []

    # ------------------------------------------------------------------
    # List + resolve
    # ------------------------------------------------------------------

    async def list_anomalies(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        resolved: bool | None = None,
    ) -> list[Anomaly]:
        conditions: list[Any] = [
            Anomaly.tenant_id == tenant_id,
            Anomaly.agent_id == agent_id,
        ]
        if resolved is not None:
            conditions.append(Anomaly.resolved.is_(resolved))
        result = await self._db.execute(
            select(Anomaly).where(*conditions).order_by(Anomaly.created_at.desc())
        )
        return list(result.scalars().all())

    async def resolve(
        self, tenant_id: uuid.UUID, anomaly_id: uuid.UUID
    ) -> Anomaly:
        result = await self._db.execute(
            select(Anomaly).where(
                Anomaly.id == anomaly_id,
                Anomaly.tenant_id == tenant_id,
            )
        )
        anomaly = result.scalar_one_or_none()
        if anomaly is None:
            raise ValueError(f"Anomaly {anomaly_id} not found")
        anomaly.resolved = True
        anomaly.resolved_at = datetime.now(UTC)
        await self._db.flush()
        return anomaly
