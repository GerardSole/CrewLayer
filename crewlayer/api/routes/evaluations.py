"""Evaluation, anomaly and A/B test endpoints."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.api.deps import ApiKeyDep, DbDep, TenantDep, check_scope
from crewlayer.api.schemas.evaluations import (
    ABTestCompleteRequest,
    ABTestCreate,
    ABTestListResponse,
    ABTestResponse,
    ABTestResultsResponse,
    AnomalyListResponse,
    AnomalyResponse,
    AutoEvaluateRequest,
    AutoEvaluateResponse,
    BatchAutoEvaluateRequest,
    BatchAutoEvaluateResponse,
    DayTrend,
    EvaluationCreate,
    EvaluationListResponse,
    EvaluationResponse,
    EvaluationSummaryResponse,
    VariantResultsResponse,
    VersionScoreResponse,
)
from crewlayer.core.evaluation.abtesting import (
    ABTestManager,
    ABTestNotActiveError,
    ABTestNotFoundError,
    PromptVersionNotFoundError,
)
from crewlayer.core.evaluation.anomalies import AnomalyManager
from crewlayer.core.evaluation.autojudge import auto_evaluate, batch_auto_evaluate
from crewlayer.core.evaluation.ratings import ActionNotFoundError, RatingsManager
from crewlayer.core.webhooks.dispatcher import dispatch
from crewlayer.db.models import Action, Agent, Evaluation, EvaluatorEnum, RatingThumbsEnum

log = logging.getLogger(__name__)

router = APIRouter()


async def _get_agent(
    agent_id: uuid.UUID, tenant_id: uuid.UUID, db: AsyncSession
) -> Agent:
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id)
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agente no encontrado")
    return agent


# ── Evaluations ───────────────────────────────────────────────────────────────

@router.post(
    "/agents/{agent_id}/actions/{action_id}/evaluate",
    status_code=status.HTTP_201_CREATED,
    response_model=EvaluationResponse,
    dependencies=[check_scope("actions:write")],
)
async def submit_evaluation(
    agent_id: uuid.UUID,
    action_id: uuid.UUID,
    body: EvaluationCreate,
    tenant: TenantDep,
    db: DbDep,
    api_key: ApiKeyDep,
) -> EvaluationResponse:
    """Submit a human evaluation for an action (thumbs up/down and/or 1-5 score)."""
    await _get_agent(agent_id, tenant.id, db)
    mgr = RatingsManager(db)
    try:
        ev = await mgr.submit(
            tenant_id=tenant.id,
            agent_id=agent_id,
            action_id=action_id,
            rating_thumbs=body.rating_thumbs,
            rating_score=body.rating_score,
            notes=body.notes,
            prompt_version_id=body.prompt_version_id,
            created_by=api_key.id,
        )
    except ActionNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Acción no encontrada")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    await db.refresh(ev)
    return EvaluationResponse.model_validate(ev)


async def _batch_auto_evaluate_bg(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    limit: int,
    since: datetime | None,
    criteria: list[str] | None,
) -> None:
    """Run batch auto-evaluation in a dedicated NullPool session."""
    import logging as _logging

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from crewlayer.core.config import settings as _settings

    _log = _logging.getLogger(__name__)
    bg_engine = create_async_engine(_settings.DATABASE_URL, poolclass=NullPool)
    BGSession = async_sessionmaker(bg_engine, expire_on_commit=False)
    try:
        async with BGSession() as db:
            count = await batch_auto_evaluate(
                db, tenant_id, agent_id, limit=limit, since=since, criteria=criteria
            )
            await db.commit()
            _log.info("Batch auto-evaluate: created %d evaluations for agent %s", count, agent_id)
        asyncio.create_task(
            dispatch(tenant_id, "evaluation.batch_completed", {
                "agent_id": str(agent_id),
                "count": count,
            })
        )
    except Exception:
        _log.exception("Batch auto-evaluate background task failed for agent %s", agent_id)
    finally:
        with contextlib.suppress(Exception):
            await bg_engine.dispose()


@router.post(
    "/agents/{agent_id}/actions/{action_id}/auto-evaluate",
    status_code=status.HTTP_201_CREATED,
    response_model=AutoEvaluateResponse,
    dependencies=[check_scope("actions:write")],
)
async def auto_evaluate_action(
    agent_id: uuid.UUID,
    action_id: uuid.UUID,
    body: AutoEvaluateRequest,
    tenant: TenantDep,
    db: DbDep,
) -> AutoEvaluateResponse:
    """Auto-evaluate an action using Claude as judge (LLM-as-a-judge)."""
    await _get_agent(agent_id, tenant.id, db)

    result = await db.execute(
        select(Action).where(
            Action.id == action_id,
            Action.tenant_id == tenant.id,
            Action.agent_id == agent_id,
        )
    )
    action = result.scalar_one_or_none()
    if action is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Acción no encontrada")

    judge_result = await auto_evaluate(action, body.criteria)

    ev = Evaluation(
        tenant_id=tenant.id,
        agent_id=agent_id,
        action_id=action_id,
        session_id=action.session_id,
        prompt_version_id=action.prompt_version_id,
        rating_score=judge_result.score,
        rating_thumbs=(
            RatingThumbsEnum.up if judge_result.thumbs == "up" else RatingThumbsEnum.down
        ),
        evaluator=EvaluatorEnum.auto,
        notes=judge_result.reasoning,
        criteria_scores=judge_result.criteria_scores,
    )
    db.add(ev)
    await db.commit()
    await db.refresh(ev)

    asyncio.create_task(
        dispatch(tenant.id, "evaluation.auto_completed", {
            "action_id": str(action_id),
            "agent_id": str(agent_id),
            "score": judge_result.score,
        })
    )

    return AutoEvaluateResponse(
        evaluation_id=ev.id,
        action_id=action_id,
        score=judge_result.score,
        thumbs=judge_result.thumbs,
        reasoning=judge_result.reasoning,
        criteria_scores=judge_result.criteria_scores,
    )


@router.post(
    "/agents/{agent_id}/actions/auto-evaluate-batch",
    response_model=BatchAutoEvaluateResponse,
    dependencies=[check_scope("actions:write")],
)
async def auto_evaluate_batch(
    agent_id: uuid.UUID,
    body: BatchAutoEvaluateRequest,
    tenant: TenantDep,
    db: DbDep,
    background_tasks: BackgroundTasks,
) -> BatchAutoEvaluateResponse:
    """Kick off background batch auto-evaluation for actions without an auto-evaluation.

    Returns immediately with the count of pending actions. Actual evaluation
    runs asynchronously using Claude as judge.
    """
    await _get_agent(agent_id, tenant.id, db)

    since: datetime | None = None
    if body.since:
        try:
            since = datetime.fromisoformat(body.since)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="since must be an ISO 8601 datetime string",
            )

    already_auto = select(Evaluation.action_id).where(
        Evaluation.tenant_id == tenant.id,
        Evaluation.agent_id == agent_id,
        Evaluation.evaluator == EvaluatorEnum.auto,
    )
    pending_stmt = (
        select(func.count())
        .select_from(Action)
        .where(
            Action.tenant_id == tenant.id,
            Action.agent_id == agent_id,
            Action.id.not_in(already_auto),
        )
    )
    if since:
        pending_stmt = pending_stmt.where(Action.created_at >= since)  # type: ignore[attr-defined]

    actions_pending = int((await db.execute(pending_stmt)).scalar_one() or 0)
    capped = min(actions_pending, body.limit)

    background_tasks.add_task(
        _batch_auto_evaluate_bg,
        tenant.id,
        agent_id,
        body.limit,
        since,
        body.criteria,
    )

    return BatchAutoEvaluateResponse(job_started=True, actions_pending=capped)


@router.get(
    "/agents/{agent_id}/evaluations",
    response_model=EvaluationListResponse,
    dependencies=[check_scope("actions:read")],
)
async def list_evaluations(
    agent_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
    from_date: Annotated[date | None, Query()] = None,
    to_date: Annotated[date | None, Query()] = None,
    prompt_version_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EvaluationListResponse:
    """List evaluations for an agent with optional date and prompt version filters."""
    await _get_agent(agent_id, tenant.id, db)
    mgr = RatingsManager(db)
    items = await mgr.list_evaluations(
        tenant_id=tenant.id,
        agent_id=agent_id,
        from_date=from_date,
        to_date=to_date,
        prompt_version_id=prompt_version_id,
        limit=limit,
        offset=offset,
    )
    return EvaluationListResponse(
        items=[EvaluationResponse.model_validate(e) for e in items],
        count=len(items),
    )


@router.get(
    "/agents/{agent_id}/evaluations/summary",
    response_model=EvaluationSummaryResponse,
    dependencies=[check_scope("actions:read")],
)
async def get_evaluation_summary(
    agent_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
) -> EvaluationSummaryResponse:
    """Return aggregated evaluation metrics: mean score, thumbs ratio, 7-day trend, breakdown by prompt version."""
    await _get_agent(agent_id, tenant.id, db)
    mgr = RatingsManager(db)
    scores = await mgr.get_agent_scores(tenant.id, agent_id)

    # 7-day daily trend
    today = datetime.now(UTC).date()
    trend_7d: list[DayTrend] = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_start = datetime.combine(day, datetime.min.time())
        day_end = datetime.combine(day, datetime.max.time())
        row = (
            await db.execute(
                select(
                    func.count().label("count"),
                    func.avg(Evaluation.rating_score).label("avg_score"),
                    func.sum(
                        case((Evaluation.rating_thumbs == RatingThumbsEnum.up, 1), else_=0)
                    ).label("thumbs_up"),
                    func.sum(
                        case((Evaluation.rating_thumbs == RatingThumbsEnum.down, 1), else_=0)
                    ).label("thumbs_down"),
                ).where(
                    Evaluation.tenant_id == tenant.id,
                    Evaluation.agent_id == agent_id,
                    Evaluation.created_at >= day_start,
                    Evaluation.created_at <= day_end,
                )
            )
        ).one()
        trend_7d.append(DayTrend(
            day=day.isoformat(),
            count=int(row._mapping["count"] or 0),
            avg_score=float(row.avg_score) if row.avg_score is not None else None,
            thumbs_up=int(row.thumbs_up or 0),
            thumbs_down=int(row.thumbs_down or 0),
        ))

    return EvaluationSummaryResponse(
        agent_id=agent_id,
        total_evaluations=scores.count,
        avg_score=scores.avg_score,
        thumbs_up=scores.thumbs_up,
        thumbs_down=scores.thumbs_down,
        thumbs_up_ratio=scores.thumbs_up_ratio,
        trend_7d=trend_7d,
        by_prompt_version=[
            VersionScoreResponse(
                prompt_version_id=v.prompt_version_id,
                count=v.count,
                avg_score=v.avg_score,
                thumbs_up=v.thumbs_up,
                thumbs_down=v.thumbs_down,
            )
            for v in scores.by_prompt_version
        ],
        auto_evaluated_count=scores.auto_evaluated_count,
        human_evaluated_count=scores.human_evaluated_count,
        criteria_averages=scores.criteria_averages,
    )


# ── Anomalies ─────────────────────────────────────────────────────────────────

@router.get(
    "/agents/{agent_id}/anomalies",
    response_model=AnomalyListResponse,
    dependencies=[check_scope("actions:read")],
)
async def list_anomalies(
    agent_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
    resolved: Annotated[bool | None, Query()] = None,
) -> AnomalyListResponse:
    """List anomalies for an agent. Use ?resolved=false to see only unresolved."""
    await _get_agent(agent_id, tenant.id, db)
    mgr = AnomalyManager(db)
    items = await mgr.list_anomalies(tenant.id, agent_id, resolved=resolved)
    return AnomalyListResponse(
        items=[AnomalyResponse.model_validate(a) for a in items],
        count=len(items),
    )


@router.post(
    "/agents/{agent_id}/anomalies/{anomaly_id}/resolve",
    response_model=AnomalyResponse,
    dependencies=[check_scope("actions:write")],
)
async def resolve_anomaly(
    agent_id: uuid.UUID,
    anomaly_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
) -> AnomalyResponse:
    """Mark an anomaly as resolved."""
    await _get_agent(agent_id, tenant.id, db)
    mgr = AnomalyManager(db)
    try:
        anomaly = await mgr.resolve(tenant.id, anomaly_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Anomalía no encontrada")
    await db.commit()
    await db.refresh(anomaly)
    return AnomalyResponse.model_validate(anomaly)


# ── A/B Tests ─────────────────────────────────────────────────────────────────

@router.post(
    "/agents/{agent_id}/ab-tests",
    status_code=status.HTTP_201_CREATED,
    response_model=ABTestResponse,
    dependencies=[check_scope("agents:write")],
)
async def create_ab_test(
    agent_id: uuid.UUID,
    body: ABTestCreate,
    tenant: TenantDep,
    db: DbDep,
) -> ABTestResponse:
    """Create a new A/B test between two prompt versions."""
    await _get_agent(agent_id, tenant.id, db)
    mgr = ABTestManager(db)
    try:
        test = await mgr.create_test(
            tenant_id=tenant.id,
            agent_id=agent_id,
            name=body.name,
            variant_a_prompt_id=body.variant_a_prompt_version_id,
            variant_b_prompt_id=body.variant_b_prompt_version_id,
            traffic_split=body.traffic_split,
        )
    except PromptVersionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    await db.refresh(test)
    return ABTestResponse.model_validate(test)


@router.get(
    "/agents/{agent_id}/ab-tests",
    response_model=ABTestListResponse,
    dependencies=[check_scope("agents:read")],
)
async def list_ab_tests(
    agent_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
) -> ABTestListResponse:
    """List all A/B tests for an agent, newest first."""
    await _get_agent(agent_id, tenant.id, db)
    mgr = ABTestManager(db)
    tests = await mgr.list_tests(tenant.id, agent_id)
    return ABTestListResponse(
        items=[ABTestResponse.model_validate(t) for t in tests],
        count=len(tests),
    )


@router.get(
    "/agents/{agent_id}/ab-tests/{test_id}/results",
    response_model=ABTestResultsResponse,
    dependencies=[check_scope("agents:read")],
)
async def get_ab_test_results(
    agent_id: uuid.UUID,
    test_id: uuid.UUID,
    tenant: TenantDep,
    db: DbDep,
) -> ABTestResultsResponse:
    """Return comparative metrics: score, thumbs ratio, error rate for each variant."""
    await _get_agent(agent_id, tenant.id, db)
    mgr = ABTestManager(db)
    try:
        results = await mgr.get_results(tenant.id, test_id)
    except ABTestNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test no encontrado")
    return ABTestResultsResponse(
        ab_test_id=results.ab_test_id,
        name=results.name,
        status=results.status,
        variant_a=VariantResultsResponse(**vars(results.variant_a)),
        variant_b=VariantResultsResponse(**vars(results.variant_b)),
    )


@router.post(
    "/agents/{agent_id}/ab-tests/{test_id}/complete",
    response_model=ABTestResponse,
    dependencies=[check_scope("agents:write")],
)
async def complete_ab_test(
    agent_id: uuid.UUID,
    test_id: uuid.UUID,
    body: ABTestCompleteRequest,
    tenant: TenantDep,
    db: DbDep,
) -> ABTestResponse:
    """Close an A/B test. If winner is 'a' or 'b', activates that prompt version."""
    await _get_agent(agent_id, tenant.id, db)
    mgr = ABTestManager(db)
    try:
        test = await mgr.complete_test(tenant.id, test_id, body.winner)
    except ABTestNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test no encontrado")
    except ABTestNotActiveError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El test no está activo")
    await db.commit()
    await db.refresh(test)
    return ABTestResponse.model_validate(test)
