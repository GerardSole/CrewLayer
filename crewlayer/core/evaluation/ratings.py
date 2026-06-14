"""Human and automatic rating submission + score aggregation."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.db.models import Action, Evaluation, EvaluatorEnum, RatingThumbsEnum


class ActionNotFoundError(Exception):
    pass


class AlreadyEvaluatedError(Exception):
    pass


@dataclass
class VersionScores:
    prompt_version_id: str | None
    count: int
    avg_score: float | None
    thumbs_up: int
    thumbs_down: int


@dataclass
class AgentScores:
    agent_id: str
    count: int
    avg_score: float | None
    thumbs_up: int
    thumbs_down: int
    thumbs_up_ratio: float
    by_prompt_version: list[VersionScores]
    auto_evaluated_count: int = 0
    human_evaluated_count: int = 0
    criteria_averages: dict[str, float] = field(default_factory=dict)


class RatingsManager:

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def submit(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        action_id: uuid.UUID,
        *,
        rating_thumbs: RatingThumbsEnum | None = None,
        rating_score: float | None = None,
        notes: str | None = None,
        prompt_version_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        created_by: uuid.UUID | None = None,
        evaluator: EvaluatorEnum = EvaluatorEnum.human,
    ) -> Evaluation:
        """Persist a human evaluation for an action."""
        action_result = await self._db.execute(
            select(Action).where(
                Action.id == action_id,
                Action.tenant_id == tenant_id,
                Action.agent_id == agent_id,
            )
        )
        action = action_result.scalar_one_or_none()
        if action is None:
            raise ActionNotFoundError(f"Action {action_id} not found")

        if rating_score is not None and not (1.0 <= rating_score <= 5.0):
            raise ValueError("rating_score must be between 1.0 and 5.0")

        ev = Evaluation(
            tenant_id=tenant_id,
            agent_id=agent_id,
            action_id=action_id,
            session_id=session_id or action.session_id,
            prompt_version_id=prompt_version_id or action.prompt_version_id,
            rating_thumbs=rating_thumbs,
            rating_score=rating_score,
            evaluator=evaluator,
            notes=notes,
            created_by=created_by,
        )
        self._db.add(ev)
        await self._db.flush()
        return ev

    async def get_agent_scores(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> AgentScores:
        """Return aggregated scores for an agent, optionally filtered by date range."""
        conditions: list[Any] = [
            Evaluation.tenant_id == tenant_id,
            Evaluation.agent_id == agent_id,
        ]
        if from_date:
            conditions.append(Evaluation.created_at >= datetime.combine(from_date, datetime.min.time()))
        if to_date:
            conditions.append(Evaluation.created_at <= datetime.combine(to_date, datetime.max.time()))

        row = (
            await self._db.execute(
                select(
                    func.count().label("total"),
                    func.avg(Evaluation.rating_score).label("avg_score"),
                    func.sum(
                        case((Evaluation.rating_thumbs == RatingThumbsEnum.up, 1), else_=0)
                    ).label("thumbs_up"),
                    func.sum(
                        case((Evaluation.rating_thumbs == RatingThumbsEnum.down, 1), else_=0)
                    ).label("thumbs_down"),
                    func.sum(
                        case((Evaluation.evaluator == EvaluatorEnum.auto, 1), else_=0)
                    ).label("auto_count"),
                    func.sum(
                        case((Evaluation.evaluator == EvaluatorEnum.human, 1), else_=0)
                    ).label("human_count"),
                ).where(*conditions)
            )
        ).one()

        total: int = int(row.total or 0)
        thumbs_up: int = int(row.thumbs_up or 0)
        thumbs_down: int = int(row.thumbs_down or 0)
        thumbs_total = thumbs_up + thumbs_down
        thumbs_up_ratio = thumbs_up / thumbs_total if thumbs_total > 0 else 0.0
        auto_count: int = int(row.auto_count or 0)
        human_count: int = int(row.human_count or 0)

        version_rows = (
            await self._db.execute(
                select(
                    Evaluation.prompt_version_id,
                    func.count().label("count"),
                    func.avg(Evaluation.rating_score).label("avg_score"),
                    func.sum(
                        case((Evaluation.rating_thumbs == RatingThumbsEnum.up, 1), else_=0)
                    ).label("thumbs_up"),
                    func.sum(
                        case((Evaluation.rating_thumbs == RatingThumbsEnum.down, 1), else_=0)
                    ).label("thumbs_down"),
                )
                .where(*conditions)
                .group_by(Evaluation.prompt_version_id)
            )
        ).all()

        by_version = [
            VersionScores(
                prompt_version_id=str(r.prompt_version_id) if r.prompt_version_id else None,
                count=int(r._mapping["count"]),
                avg_score=float(r.avg_score) if r.avg_score is not None else None,
                thumbs_up=int(r.thumbs_up or 0),
                thumbs_down=int(r.thumbs_down or 0),
            )
            for r in version_rows
        ]

        # Aggregate per-criterion averages from criteria_scores JSONB rows
        cs_rows = (
            await self._db.execute(
                select(Evaluation.criteria_scores).where(
                    *conditions,
                    Evaluation.criteria_scores.isnot(None),
                )
            )
        ).scalars().all()
        criteria_sums: dict[str, list[float]] = {}
        for cs in cs_rows:
            if cs:
                for k, v in cs.items():
                    criteria_sums.setdefault(k, []).append(float(v))
        criteria_averages = {
            k: round(sum(v) / len(v), 3) for k, v in criteria_sums.items()
        }

        return AgentScores(
            agent_id=str(agent_id),
            count=total,
            avg_score=float(row.avg_score) if row.avg_score is not None else None,
            thumbs_up=thumbs_up,
            thumbs_down=thumbs_down,
            thumbs_up_ratio=thumbs_up_ratio,
            by_prompt_version=by_version,
            auto_evaluated_count=auto_count,
            human_evaluated_count=human_count,
            criteria_averages=criteria_averages,
        )

    async def list_evaluations(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        from_date: date | None = None,
        to_date: date | None = None,
        prompt_version_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Evaluation]:
        conditions: list[Any] = [
            Evaluation.tenant_id == tenant_id,
            Evaluation.agent_id == agent_id,
        ]
        if from_date:
            conditions.append(Evaluation.created_at >= datetime.combine(from_date, datetime.min.time()))
        if to_date:
            conditions.append(Evaluation.created_at <= datetime.combine(to_date, datetime.max.time()))
        if prompt_version_id:
            conditions.append(Evaluation.prompt_version_id == prompt_version_id)

        result = await self._db.execute(
            select(Evaluation)
            .where(*conditions)
            .order_by(Evaluation.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())
