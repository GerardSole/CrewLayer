"""Response dataclasses returned by the CrewLayer SDK."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

@dataclass
class Message:
    """A single message in short-term (session) memory."""
    role: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def _from(cls, d: dict[str, Any]) -> Message:
        return cls(role=d["role"], content=d["content"], metadata=d.get("metadata", {}))


@dataclass
class ShortMemory:
    """Short-term memory for a session — a list of recent messages."""
    session_id: str
    messages: list[Message]
    count: int

    @classmethod
    def _from(cls, d: dict[str, Any]) -> ShortMemory:
        return cls(
            session_id=d["session_id"],
            messages=[Message._from(m) for m in d["messages"]],
            count=d["count"],
        )


@dataclass
class MemoryItem:
    """A single long-term memory record."""
    id: str
    agent_id: str
    content: str
    importance: float
    tags: list[str]
    created_at: str
    summary: str | None = None
    similarity: float | None = None

    @classmethod
    def _from(cls, d: dict[str, Any]) -> MemoryItem:
        return cls(
            id=d["id"],
            agent_id=d["agent_id"],
            content=d["content"],
            importance=d["importance"],
            tags=d["tags"],
            created_at=d["created_at"],
            summary=d.get("summary"),
            similarity=d.get("similarity"),
        )


@dataclass
class RecallResult:
    """Semantic recall results ranked by similarity to the query."""
    query: str
    results: list[MemoryItem]

    @classmethod
    def _from(cls, d: dict[str, Any]) -> RecallResult:
        return cls(query=d["query"], results=[MemoryItem._from(r) for r in d["results"]])


@dataclass
class ExtractResult:
    """Result of extracting facts from a conversation."""
    extracted_count: int
    memory_ids: list[str]

    @classmethod
    def _from(cls, d: dict[str, Any]) -> ExtractResult:
        return cls(extracted_count=d["extracted_count"], memory_ids=d["memory_ids"])


@dataclass
class MemoryPage:
    """Paginated list of long-term memory records."""
    items: list[MemoryItem]
    total: int
    page: int
    page_size: int

    @classmethod
    def _from(cls, d: dict[str, Any]) -> MemoryPage:
        return cls(
            items=[MemoryItem._from(i) for i in d["items"]],
            total=d["total"],
            page=d["page"],
            page_size=d["page_size"],
        )


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

@dataclass
class ActionRecord:
    """An immutable action log entry."""
    id: str
    tenant_id: str
    agent_id: str
    tool_name: str
    input_params: dict[str, Any]
    output_result: dict[str, Any]
    status: str
    timestamp: str
    session_id: str | None = None
    duration_ms: int | None = None
    error_msg: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def _from(cls, d: dict[str, Any]) -> ActionRecord:
        return cls(
            id=d["id"],
            tenant_id=d["tenant_id"],
            agent_id=d["agent_id"],
            tool_name=d["tool_name"],
            input_params=d["input_params"],
            output_result=d["output_result"],
            status=d["status"],
            timestamp=d["timestamp"],
            session_id=d.get("session_id"),
            duration_ms=d.get("duration_ms"),
            error_msg=d.get("error_msg"),
            metadata=d.get("metadata", {}),
        )


@dataclass
class ActionPage:
    """Cursor-paginated list of action records."""
    items: list[ActionRecord]
    count: int
    next_cursor: str | None

    @classmethod
    def _from(cls, d: dict[str, Any]) -> ActionPage:
        return cls(
            items=[ActionRecord._from(i) for i in d["items"]],
            count=d["count"],
            next_cursor=d.get("next_cursor"),
        )


@dataclass
class ToolStat:
    """Aggregate statistics for a single tool."""
    tool_name: str
    count: int
    error_rate: float
    avg_duration_ms: float | None = None

    @classmethod
    def _from(cls, d: dict[str, Any]) -> ToolStat:
        return cls(
            tool_name=d["tool_name"],
            count=d["count"],
            error_rate=d["error_rate"],
            avg_duration_ms=d.get("avg_duration_ms"),
        )


@dataclass
class ActionStats:
    """Aggregate action statistics for an agent."""
    total_actions: int
    error_rate: float
    by_tool: list[ToolStat]
    avg_duration_ms: float | None = None

    @classmethod
    def _from(cls, d: dict[str, Any]) -> ActionStats:
        return cls(
            total_actions=d["total_actions"],
            error_rate=d["error_rate"],
            avg_duration_ms=d.get("avg_duration_ms"),
            by_tool=[ToolStat._from(t) for t in d["by_tool"]],
        )


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

@dataclass
class PromptVersion:
    """A single prompt version record."""
    id: str
    tenant_id: str
    agent_id: str
    version: int
    content: str
    is_active: bool
    created_at: str
    description: str | None = None
    created_by: str | None = None

    @classmethod
    def _from(cls, d: dict[str, Any]) -> PromptVersion:
        return cls(
            id=d["id"],
            tenant_id=d["tenant_id"],
            agent_id=d["agent_id"],
            version=d["version"],
            content=d["content"],
            is_active=d["is_active"],
            created_at=d["created_at"],
            description=d.get("description"),
            created_by=d.get("created_by"),
        )


@dataclass
class PromptVersionPage:
    """List of prompt versions."""
    items: list[PromptVersion]
    count: int

    @classmethod
    def _from(cls, d: dict[str, Any]) -> PromptVersionPage:
        return cls(
            items=[PromptVersion._from(i) for i in d["items"]],
            count=d["count"],
        )


@dataclass
class DiffLine:
    """A single line in a prompt diff."""
    operation: str   # "equal" | "insert" | "delete"
    content: str
    line_a: int | None = None
    line_b: int | None = None

    @classmethod
    def _from(cls, d: dict[str, Any]) -> DiffLine:
        return cls(
            operation=d["operation"],
            content=d["content"],
            line_a=d.get("line_a"),
            line_b=d.get("line_b"),
        )


@dataclass
class PromptDiff:
    """Line-by-line diff between two prompt versions."""
    version_id_a: str
    version_id_b: str
    lines: list[DiffLine]

    @classmethod
    def _from(cls, d: dict[str, Any]) -> PromptDiff:
        return cls(
            version_id_a=d["version_id_a"],
            version_id_b=d["version_id_b"],
            lines=[DiffLine._from(l) for l in d["lines"]],
        )


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------

@dataclass
class ContextEntry:
    """A single blackboard context entry."""
    id: str
    tenant_id: str
    namespace: str
    key: str
    value: dict[str, Any]
    version: int
    created_at: str
    updated_at: str
    written_by: str | None = None
    expires_at: str | None = None

    @classmethod
    def _from(cls, d: dict[str, Any]) -> ContextEntry:
        return cls(
            id=d["id"],
            tenant_id=d["tenant_id"],
            namespace=d["namespace"],
            key=d["key"],
            value=d["value"],
            version=d["version"],
            created_at=d["created_at"],
            updated_at=d["updated_at"],
            written_by=d.get("written_by"),
            expires_at=d.get("expires_at"),
        )


@dataclass
class ContextNamespace:
    """All non-expired entries in a namespace."""
    namespace: str
    entries: list[ContextEntry]
    count: int

    @classmethod
    def _from(cls, d: dict[str, Any]) -> ContextNamespace:
        return cls(
            namespace=d["namespace"],
            entries=[ContextEntry._from(e) for e in d["entries"]],
            count=d["count"],
        )


# ---------------------------------------------------------------------------
# Evaluations
# ---------------------------------------------------------------------------

@dataclass
class EvaluationRecord:
    """A single evaluation (human or automated) for an action."""
    id: str
    tenant_id: str
    agent_id: str
    action_id: str
    evaluator: str
    created_at: str
    session_id: str | None = None
    prompt_version_id: str | None = None
    rating_thumbs: str | None = None
    rating_score: float | None = None
    notes: str | None = None
    criteria_scores: dict[str, float] | None = None
    created_by: str | None = None

    @classmethod
    def _from(cls, d: dict[str, Any]) -> EvaluationRecord:
        return cls(
            id=d["id"],
            tenant_id=d["tenant_id"],
            agent_id=d["agent_id"],
            action_id=d["action_id"],
            evaluator=d["evaluator"],
            created_at=d["created_at"],
            session_id=d.get("session_id"),
            prompt_version_id=d.get("prompt_version_id"),
            rating_thumbs=d.get("rating_thumbs"),
            rating_score=d.get("rating_score"),
            notes=d.get("notes"),
            criteria_scores=d.get("criteria_scores"),
            created_by=d.get("created_by"),
        )


@dataclass
class AutoEvaluateResult:
    """Result of an LLM-as-a-judge auto-evaluation."""
    evaluation_id: str
    action_id: str
    score: float
    thumbs: str
    reasoning: str
    criteria_scores: dict[str, float]

    @classmethod
    def _from(cls, d: dict[str, Any]) -> AutoEvaluateResult:
        return cls(
            evaluation_id=d["evaluation_id"],
            action_id=d["action_id"],
            score=d["score"],
            thumbs=d["thumbs"],
            reasoning=d["reasoning"],
            criteria_scores=d["criteria_scores"],
        )


@dataclass
class BatchAutoEvaluateResult:
    """Result of a batch auto-evaluate request."""
    job_started: bool
    actions_pending: int

    @classmethod
    def _from(cls, d: dict[str, Any]) -> BatchAutoEvaluateResult:
        return cls(
            job_started=d["job_started"],
            actions_pending=d["actions_pending"],
        )


@dataclass
class DayTrend:
    """Daily evaluation aggregates."""
    day: str
    count: int
    thumbs_up: int
    thumbs_down: int
    avg_score: float | None = None

    @classmethod
    def _from(cls, d: dict[str, Any]) -> DayTrend:
        return cls(
            day=d["day"],
            count=d["count"],
            thumbs_up=d["thumbs_up"],
            thumbs_down=d["thumbs_down"],
            avg_score=d.get("avg_score"),
        )


@dataclass
class EvaluationSummary:
    """Aggregated evaluation metrics for an agent."""
    agent_id: str
    total_evaluations: int
    thumbs_up: int
    thumbs_down: int
    thumbs_up_ratio: float
    trend_7d: list[DayTrend]
    avg_score: float | None = None
    auto_evaluated_count: int = 0
    human_evaluated_count: int = 0
    criteria_averages: dict[str, float] | None = None

    @classmethod
    def _from(cls, d: dict[str, Any]) -> EvaluationSummary:
        return cls(
            agent_id=d["agent_id"],
            total_evaluations=d["total_evaluations"],
            thumbs_up=d["thumbs_up"],
            thumbs_down=d["thumbs_down"],
            thumbs_up_ratio=d["thumbs_up_ratio"],
            trend_7d=[DayTrend._from(t) for t in d.get("trend_7d", [])],
            avg_score=d.get("avg_score"),
            auto_evaluated_count=d.get("auto_evaluated_count", 0),
            human_evaluated_count=d.get("human_evaluated_count", 0),
            criteria_averages=d.get("criteria_averages"),
        )


@dataclass
class AnomalyRecord:
    """A detected anomaly for an agent."""
    id: str
    tenant_id: str
    agent_id: str
    action_id: str
    anomaly_type: str
    severity: str
    details: dict[str, Any]
    resolved: bool
    created_at: str
    resolved_at: str | None = None

    @classmethod
    def _from(cls, d: dict[str, Any]) -> AnomalyRecord:
        return cls(
            id=d["id"],
            tenant_id=d["tenant_id"],
            agent_id=d["agent_id"],
            action_id=d["action_id"],
            anomaly_type=d["anomaly_type"],
            severity=d["severity"],
            details=d["details"],
            resolved=d["resolved"],
            created_at=d["created_at"],
            resolved_at=d.get("resolved_at"),
        )


@dataclass
class ABTestRecord:
    """An A/B test comparing two prompt versions."""
    id: str
    tenant_id: str
    agent_id: str
    name: str
    status: str
    variant_a_prompt_version_id: str
    variant_b_prompt_version_id: str
    traffic_split: float
    started_at: str
    completed_at: str | None = None
    winner: str | None = None

    @classmethod
    def _from(cls, d: dict[str, Any]) -> ABTestRecord:
        return cls(
            id=d["id"],
            tenant_id=d["tenant_id"],
            agent_id=d["agent_id"],
            name=d["name"],
            status=d["status"],
            variant_a_prompt_version_id=d["variant_a_prompt_version_id"],
            variant_b_prompt_version_id=d["variant_b_prompt_version_id"],
            traffic_split=d["traffic_split"],
            started_at=d["started_at"],
            completed_at=d.get("completed_at"),
            winner=d.get("winner"),
        )


@dataclass
class VariantResults:
    """Comparative metrics for one variant in an A/B test."""
    variant: str
    prompt_version_id: str
    total_actions: int
    error_rate: float
    thumbs_up_ratio: float
    avg_score: float | None = None

    @classmethod
    def _from(cls, d: dict[str, Any]) -> VariantResults:
        return cls(
            variant=d["variant"],
            prompt_version_id=d["prompt_version_id"],
            total_actions=d["total_actions"],
            error_rate=d["error_rate"],
            thumbs_up_ratio=d["thumbs_up_ratio"],
            avg_score=d.get("avg_score"),
        )


@dataclass
class ABTestResults:
    """Full results of an A/B test."""
    ab_test_id: str
    name: str
    status: str
    variant_a: VariantResults
    variant_b: VariantResults

    @classmethod
    def _from(cls, d: dict[str, Any]) -> ABTestResults:
        return cls(
            ab_test_id=d["ab_test_id"],
            name=d["name"],
            status=d["status"],
            variant_a=VariantResults._from(d["variant_a"]),
            variant_b=VariantResults._from(d["variant_b"]),
        )
