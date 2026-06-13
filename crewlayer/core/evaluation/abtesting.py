"""A/B test management for prompt versions.

Variant assignment is deterministic: SHA-256(session_id) % 100 compared
against traffic_split * 100 so the same session always gets the same variant.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from crewlayer.db.models import (
    ABTest,
    ABTestAssignment,
    ABTestStatusEnum,
    ABTestVariantEnum,
    ABTestWinnerEnum,
    Action,
    ActionStatus,
    Evaluation,
    PromptVersion,
    RatingThumbsEnum,
)


class ABTestNotFoundError(Exception):
    pass


class ABTestNotActiveError(Exception):
    pass


class PromptVersionNotFoundError(Exception):
    pass


@dataclass
class VariantResults:
    variant: str
    prompt_version_id: str
    total_actions: int
    error_rate: float
    avg_score: float | None
    thumbs_up_ratio: float


@dataclass
class ABTestResults:
    ab_test_id: str
    name: str
    status: str
    variant_a: VariantResults
    variant_b: VariantResults


class ABTestManager:

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_test(
        self, tenant_id: uuid.UUID, test_id: uuid.UUID
    ) -> ABTest:
        result = await self._db.execute(
            select(ABTest).where(
                ABTest.id == test_id,
                ABTest.tenant_id == tenant_id,
            )
        )
        test = result.scalar_one_or_none()
        if test is None:
            raise ABTestNotFoundError(f"A/B test {test_id} not found")
        return test

    async def _verify_prompt_version(
        self, tenant_id: uuid.UUID, version_id: uuid.UUID
    ) -> None:
        result = await self._db.execute(
            select(PromptVersion.id).where(
                PromptVersion.id == version_id,
                PromptVersion.tenant_id == tenant_id,
            )
        )
        if result.scalar_one_or_none() is None:
            raise PromptVersionNotFoundError(f"Prompt version {version_id} not found")

    @staticmethod
    def _deterministic_variant(
        session_id: uuid.UUID, traffic_split: float
    ) -> ABTestVariantEnum:
        digest = hashlib.sha256(str(session_id).encode()).digest()
        bucket = int.from_bytes(digest[:4], "big") % 100
        return (
            ABTestVariantEnum.a
            if bucket < traffic_split * 100
            else ABTestVariantEnum.b
        )

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_test(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        name: str,
        variant_a_prompt_id: uuid.UUID,
        variant_b_prompt_id: uuid.UUID,
        traffic_split: float = 0.5,
    ) -> ABTest:
        """Create a new A/B test. Only one test per agent can be active."""
        if not (0.0 < traffic_split < 1.0):
            raise ValueError("traffic_split must be between 0.0 and 1.0 (exclusive)")

        await self._verify_prompt_version(tenant_id, variant_a_prompt_id)
        await self._verify_prompt_version(tenant_id, variant_b_prompt_id)

        test = ABTest(
            tenant_id=tenant_id,
            agent_id=agent_id,
            name=name,
            status=ABTestStatusEnum.active,
            variant_a_prompt_version_id=variant_a_prompt_id,
            variant_b_prompt_version_id=variant_b_prompt_id,
            traffic_split=traffic_split,
        )
        self._db.add(test)
        await self._db.flush()
        return test

    # ------------------------------------------------------------------
    # Variant assignment
    # ------------------------------------------------------------------

    async def assign_variant(
        self, ab_test_id: uuid.UUID, session_id: uuid.UUID
    ) -> ABTestAssignment:
        """Get or create a deterministic variant assignment for a session."""
        existing = await self._db.execute(
            select(ABTestAssignment).where(
                ABTestAssignment.ab_test_id == ab_test_id,
                ABTestAssignment.session_id == session_id,
            )
        )
        assignment = existing.scalar_one_or_none()
        if assignment is not None:
            return assignment

        test_result = await self._db.execute(
            select(ABTest).where(ABTest.id == ab_test_id)
        )
        test = test_result.scalar_one_or_none()
        if test is None:
            raise ABTestNotFoundError(f"A/B test {ab_test_id} not found")

        variant = self._deterministic_variant(session_id, test.traffic_split)
        assignment = ABTestAssignment(
            ab_test_id=ab_test_id,
            session_id=session_id,
            variant=variant,
        )
        self._db.add(assignment)
        await self._db.flush()
        return assignment

    async def get_active_prompt(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        session_id: uuid.UUID,
    ) -> PromptVersion | None:
        """Return the prompt version the agent should use for this session.

        If there is an active A/B test, assign a variant and return its prompt.
        Otherwise return the globally active prompt (or None if none set).
        """
        active_test_result = await self._db.execute(
            select(ABTest).where(
                ABTest.tenant_id == tenant_id,
                ABTest.agent_id == agent_id,
                ABTest.status == ABTestStatusEnum.active,
            ).order_by(ABTest.started_at.desc()).limit(1)
        )
        test = active_test_result.scalar_one_or_none()

        if test is not None:
            assignment = await self.assign_variant(test.id, session_id)
            prompt_id = (
                test.variant_a_prompt_version_id
                if assignment.variant == ABTestVariantEnum.a
                else test.variant_b_prompt_version_id
            )
            pv_result = await self._db.execute(
                select(PromptVersion).where(PromptVersion.id == prompt_id)
            )
            return pv_result.scalar_one_or_none()

        # No active test — fall back to globally active prompt
        pv_result = await self._db.execute(
            select(PromptVersion).where(
                PromptVersion.tenant_id == tenant_id,
                PromptVersion.agent_id == agent_id,
                PromptVersion.is_active.is_(True),
            )
        )
        return pv_result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------

    async def get_results(
        self, tenant_id: uuid.UUID, test_id: uuid.UUID
    ) -> ABTestResults:
        test = await self._get_test(tenant_id, test_id)

        results = []
        for variant_enum, prompt_id in [
            (ABTestVariantEnum.a, test.variant_a_prompt_version_id),
            (ABTestVariantEnum.b, test.variant_b_prompt_version_id),
        ]:
            assigned_sessions_subq = (
                select(ABTestAssignment.session_id)
                .where(
                    ABTestAssignment.ab_test_id == test_id,
                    ABTestAssignment.variant == variant_enum,
                )
                .scalar_subquery()
            )

            action_row = (
                await self._db.execute(
                    select(
                        func.count().label("total"),
                        func.sum(
                            case(
                                (
                                    Action.status.in_([ActionStatus.error, ActionStatus.timeout]),
                                    1,
                                ),
                                else_=0,
                            )
                        ).label("errors"),
                    ).where(
                        Action.tenant_id == tenant_id,
                        Action.agent_id == test.agent_id,
                        Action.session_id.in_(assigned_sessions_subq),
                    )
                )
            ).one()

            eval_row = (
                await self._db.execute(
                    select(
                        func.avg(Evaluation.rating_score).label("avg_score"),
                        func.sum(
                            case((Evaluation.rating_thumbs == RatingThumbsEnum.up, 1), else_=0)
                        ).label("thumbs_up"),
                        func.sum(
                            case(
                                (Evaluation.rating_thumbs.is_not(None), 1),
                                else_=0,
                            )
                        ).label("thumbs_total"),
                    ).where(
                        Evaluation.tenant_id == tenant_id,
                        Evaluation.agent_id == test.agent_id,
                        Evaluation.session_id.in_(assigned_sessions_subq),
                    )
                )
            ).one()

            total = int(action_row.total or 0)
            errors = int(action_row.errors or 0)
            thumbs_total = int(eval_row.thumbs_total or 0)
            thumbs_up = int(eval_row.thumbs_up or 0)

            results.append(VariantResults(
                variant=variant_enum.value,
                prompt_version_id=str(prompt_id),
                total_actions=total,
                error_rate=errors / total if total > 0 else 0.0,
                avg_score=float(eval_row.avg_score) if eval_row.avg_score is not None else None,
                thumbs_up_ratio=thumbs_up / thumbs_total if thumbs_total > 0 else 0.0,
            ))

        return ABTestResults(
            ab_test_id=str(test.id),
            name=test.name,
            status=test.status.value,
            variant_a=results[0],
            variant_b=results[1],
        )

    # ------------------------------------------------------------------
    # Complete
    # ------------------------------------------------------------------

    async def complete_test(
        self,
        tenant_id: uuid.UUID,
        test_id: uuid.UUID,
        winner: ABTestWinnerEnum,
    ) -> ABTest:
        """Close an A/B test. If winner is 'a' or 'b', activate its prompt."""
        test = await self._get_test(tenant_id, test_id)
        if test.status != ABTestStatusEnum.active:
            raise ABTestNotActiveError("Test is not active")

        test.status = ABTestStatusEnum.completed
        test.winner = winner
        test.completed_at = datetime.now(UTC)

        if winner in (ABTestWinnerEnum.a, ABTestWinnerEnum.b):
            winning_prompt_id = (
                test.variant_a_prompt_version_id
                if winner == ABTestWinnerEnum.a
                else test.variant_b_prompt_version_id
            )
            from sqlalchemy import update as sa_update
            await self._db.execute(
                sa_update(PromptVersion)
                .where(
                    PromptVersion.tenant_id == tenant_id,
                    PromptVersion.agent_id == test.agent_id,
                )
                .values(is_active=False)
            )
            winning_pv_result = await self._db.execute(
                select(PromptVersion).where(PromptVersion.id == winning_prompt_id)
            )
            winning_pv = winning_pv_result.scalar_one_or_none()
            if winning_pv is not None:
                winning_pv.is_active = True

        await self._db.flush()
        return test

    async def list_tests(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> list[ABTest]:
        result = await self._db.execute(
            select(ABTest)
            .where(ABTest.tenant_id == tenant_id, ABTest.agent_id == agent_id)
            .order_by(ABTest.started_at.desc())
        )
        return list(result.scalars().all())
