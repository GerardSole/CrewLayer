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
    ActionPage,
    ActionRecord,
    ActionStats,
    ContextEntry,
    ContextNamespace,
    ExtractResult,
    MemoryItem,
    MemoryPage,
    Message,
    RecallResult,
    ShortMemory,
    ToolStat,
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
]

__version__ = "0.1.0"
