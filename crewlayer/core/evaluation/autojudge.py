"""LLM-as-a-judge auto-evaluation using claude-opus-4-8."""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

import anthropic

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from crewlayer.db.models import Action

log = logging.getLogger(__name__)

DEFAULT_CRITERIA = ["correctness", "efficiency", "completeness", "safety"]

_SYSTEM_PROMPT = (
    "You are a quality evaluator for AI agent actions. "
    "Score each criterion from 1.0 (very poor) to 5.0 (excellent). "
    "Respond ONLY with valid JSON — no markdown, no prose outside the object."
)

_PROMPT_TEMPLATE = """Evaluate this AI agent action.

Action:
  tool: {tool_name}
  status: {status}
  duration_ms: {duration_ms}
  input: {input_params}
  output: {output_result}{error_line}

Criteria to score (1.0–5.0 each): {criteria_list}

Return exactly this JSON structure:
{{
  "score": <overall 1.0-5.0 weighted average>,
  "thumbs": "up" or "down",
  "reasoning": "<2-3 sentence explanation>",
  "criteria_scores": {{{criteria_fields}}}
}}
thumbs is "up" when overall score >= 3.5, otherwise "down"."""


@dataclass
class AutoJudgeResult:
    score: float
    thumbs: str
    reasoning: str
    criteria_scores: dict[str, float] = field(default_factory=dict)


async def auto_evaluate(
    action: "Action",
    criteria: list[str] | None = None,
) -> AutoJudgeResult:
    """Call claude-opus-4-8 to evaluate an action's quality on given criteria."""
    if criteria is None:
        criteria = list(DEFAULT_CRITERIA)

    error_line = f"\n  error: {action.error_msg}" if action.error_msg else ""
    criteria_fields = ", ".join(f'"{c}": <score>' for c in criteria)
    status_val = action.status.value if hasattr(action.status, "value") else str(action.status)

    prompt = _PROMPT_TEMPLATE.format(
        tool_name=action.tool_name,
        status=status_val,
        duration_ms=action.duration_ms or 0,
        input_params=json.dumps(action.input_params or {}, ensure_ascii=False)[:600],
        output_result=json.dumps(action.output_result or {}, ensure_ascii=False)[:600],
        error_line=error_line,
        criteria_list=", ".join(criteria),
        criteria_fields=criteria_fields,
    )

    client = anthropic.AsyncAnthropic()
    response = await client.messages.create(
        model="claude-opus-4-8",
        max_tokens=512,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = next(b.text for b in response.content if b.type == "text").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        inner = lines[1:-1] if lines[-1].startswith("```") else lines[1:]
        raw = "\n".join(inner)

    data: dict[str, Any] = json.loads(raw)
    score = float(data["score"])
    cs = data.get("criteria_scores", {})

    return AutoJudgeResult(
        score=round(score, 3),
        thumbs=data.get("thumbs", "up" if score >= 3.5 else "down"),
        reasoning=data.get("reasoning", ""),
        criteria_scores={c: round(float(cs.get(c, score)), 3) for c in criteria},
    )


async def batch_auto_evaluate(
    db: "AsyncSession",
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    limit: int = 20,
    since: datetime | None = None,
    criteria: list[str] | None = None,
) -> int:
    """Auto-evaluate up to `limit` un-evaluated actions.

    Skips actions that already have an auto evaluation.
    Returns the number of evaluations created.
    """
    from sqlalchemy import select

    from crewlayer.db.models import Action, Evaluation, EvaluatorEnum, RatingThumbsEnum

    if criteria is None:
        criteria = list(DEFAULT_CRITERIA)

    already_auto = select(Evaluation.action_id).where(
        Evaluation.tenant_id == tenant_id,
        Evaluation.agent_id == agent_id,
        Evaluation.evaluator == EvaluatorEnum.auto,
    )

    stmt = (
        select(Action)
        .where(
            Action.tenant_id == tenant_id,
            Action.agent_id == agent_id,
            Action.id.not_in(already_auto),
        )
        .order_by(Action.created_at.desc())
        .limit(limit)
    )
    if since is not None:
        stmt = stmt.where(Action.created_at >= since)

    actions = (await db.execute(stmt)).scalars().all()
    count = 0
    for action in actions:
        try:
            result = await auto_evaluate(action, criteria)
            ev = Evaluation(
                tenant_id=tenant_id,
                agent_id=agent_id,
                action_id=action.id,
                session_id=action.session_id,
                prompt_version_id=action.prompt_version_id,
                rating_score=result.score,
                rating_thumbs=(
                    RatingThumbsEnum.up if result.thumbs == "up" else RatingThumbsEnum.down
                ),
                evaluator=EvaluatorEnum.auto,
                notes=result.reasoning,
                criteria_scores=result.criteria_scores,
            )
            db.add(ev)
            count += 1
        except Exception:
            log.exception("Failed to auto-evaluate action %s", action.id)

    if count > 0:
        await db.flush()
    return count
