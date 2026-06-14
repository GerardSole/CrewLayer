"""Pydantic v2 schemas for evaluation, anomaly, and A/B test endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from crewlayer.db.models import (
    ABTestStatusEnum,
    ABTestWinnerEnum,
    AnomalySeverityEnum,
    AnomalyTypeEnum,
    EvaluatorEnum,
    RatingThumbsEnum,
)

# ── Evaluations ───────────────────────────────────────────────────────────────

class EvaluationCreate(BaseModel):
    rating_thumbs: RatingThumbsEnum | None = None
    rating_score: float | None = Field(None, ge=1.0, le=5.0)
    notes: str | None = None
    prompt_version_id: uuid.UUID | None = None


class EvaluationResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    agent_id: uuid.UUID
    action_id: uuid.UUID
    session_id: uuid.UUID | None = None
    prompt_version_id: uuid.UUID | None = None
    rating_thumbs: RatingThumbsEnum | None = None
    rating_score: float | None = None
    evaluator: EvaluatorEnum
    notes: str | None = None
    criteria_scores: dict[str, float] | None = None
    created_at: datetime
    created_by: uuid.UUID | None = None

    model_config = {"from_attributes": True}


class EvaluationListResponse(BaseModel):
    items: list[EvaluationResponse]
    count: int


class VersionScoreResponse(BaseModel):
    prompt_version_id: str | None
    count: int
    avg_score: float | None
    thumbs_up: int
    thumbs_down: int


class DayTrend(BaseModel):
    day: str
    count: int
    avg_score: float | None
    thumbs_up: int
    thumbs_down: int


class EvaluationSummaryResponse(BaseModel):
    agent_id: uuid.UUID
    total_evaluations: int
    avg_score: float | None
    thumbs_up: int
    thumbs_down: int
    thumbs_up_ratio: float
    trend_7d: list[DayTrend]
    by_prompt_version: list[VersionScoreResponse]
    auto_evaluated_count: int = 0
    human_evaluated_count: int = 0
    criteria_averages: dict[str, float] = {}


class AutoEvaluateRequest(BaseModel):
    criteria: list[str] | None = None


class AutoEvaluateResponse(BaseModel):
    evaluation_id: uuid.UUID
    action_id: uuid.UUID
    score: float
    thumbs: str
    reasoning: str
    criteria_scores: dict[str, float]

    model_config = {"from_attributes": True}


class BatchAutoEvaluateRequest(BaseModel):
    limit: int = Field(20, ge=1, le=100)
    since: str | None = None
    criteria: list[str] | None = None


class BatchAutoEvaluateResponse(BaseModel):
    job_started: bool
    actions_pending: int


# ── Anomalies ─────────────────────────────────────────────────────────────────

class AnomalyResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    agent_id: uuid.UUID
    action_id: uuid.UUID
    anomaly_type: AnomalyTypeEnum
    severity: AnomalySeverityEnum
    details: dict[str, Any]
    resolved: bool
    resolved_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AnomalyListResponse(BaseModel):
    items: list[AnomalyResponse]
    count: int


# ── A/B Tests ─────────────────────────────────────────────────────────────────

class ABTestCreate(BaseModel):
    name: str
    variant_a_prompt_version_id: uuid.UUID
    variant_b_prompt_version_id: uuid.UUID
    traffic_split: float = Field(0.5, gt=0.0, lt=1.0)


class ABTestResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    agent_id: uuid.UUID
    name: str
    status: ABTestStatusEnum
    variant_a_prompt_version_id: uuid.UUID
    variant_b_prompt_version_id: uuid.UUID
    traffic_split: float
    started_at: datetime
    completed_at: datetime | None = None
    winner: ABTestWinnerEnum | None = None

    model_config = {"from_attributes": True}


class ABTestListResponse(BaseModel):
    items: list[ABTestResponse]
    count: int


class VariantResultsResponse(BaseModel):
    variant: str
    prompt_version_id: str
    total_actions: int
    error_rate: float
    avg_score: float | None
    thumbs_up_ratio: float


class ABTestResultsResponse(BaseModel):
    ab_test_id: str
    name: str
    status: str
    variant_a: VariantResultsResponse
    variant_b: VariantResultsResponse


class ABTestCompleteRequest(BaseModel):
    winner: ABTestWinnerEnum
