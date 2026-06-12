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
