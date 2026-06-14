"""CrewLayer SDK — official Python client for the CrewLayer AI agent backend."""
from crewlayer._client import CrewLayerAsyncClient, CrewLayerClient
from crewlayer._exceptions import (
    AuthError,
    ConflictError,
    CrewLayerError,
    NotFoundError,
    RateLimitError,
    ServerError,
)
from crewlayer._types import (
    ABTestRecord,
    ABTestResults,
    ActionPage,
    ActionRecord,
    ActionStats,
    AnomalyRecord,
    AutoEvaluateResult,
    BatchAutoEvaluateResult,
    ContextEntry,
    ContextNamespace,
    DayTrend,
    DiffLine,
    EvaluationRecord,
    EvaluationSummary,
    ExtractResult,
    MemoryItem,
    MemoryPage,
    Message,
    PromptDiff,
    PromptVersion,
    PromptVersionPage,
    RecallResult,
    ShortMemory,
    ToolStat,
    VariantResults,
)

__all__ = [
    # Clients
    "CrewLayerClient",
    "CrewLayerAsyncClient",
    # Exceptions
    "CrewLayerError",
    "AuthError",
    "NotFoundError",
    "ConflictError",
    "RateLimitError",
    "ServerError",
    # Types — memory
    "Message",
    "ShortMemory",
    "MemoryItem",
    "RecallResult",
    "ExtractResult",
    "MemoryPage",
    # Types — actions
    "ActionRecord",
    "ActionPage",
    "ToolStat",
    "ActionStats",
    # Types — context
    "ContextEntry",
    "ContextNamespace",
    # Types — prompts
    "PromptVersion",
    "PromptVersionPage",
    "DiffLine",
    "PromptDiff",
    # Types — evaluations
    "EvaluationRecord",
    "EvaluationSummary",
    "DayTrend",
    "AnomalyRecord",
    "ABTestRecord",
    "ABTestResults",
    "VariantResults",
    "AutoEvaluateResult",
    "BatchAutoEvaluateResult",
]

__version__ = "0.1.0"
