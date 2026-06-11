export { CrewLayerClient } from "./client.js";

// Resources (useful for type-level access to params/return types)
export { MemoryResource } from "./resources/memory.js";
export { ActionsResource } from "./resources/actions.js";
export { ContextResource } from "./resources/context.js";
export { AgentsResource } from "./resources/agents.js";
export { SessionsResource } from "./resources/sessions.js";
export { EpisodesResource } from "./resources/episodes.js";

// Errors
export {
  CrewLayerError,
  AuthError,
  NotFoundError,
  ConflictError,
  RateLimitError,
  ServerError,
} from "./errors.js";

// Streaming
export { SSEStream, openContextStream } from "./streaming.js";
export type { ContextSSEStream, ContextStreamEvents } from "./streaming.js";

// All public types
export type {
  Role,
  AgentStatus,
  MemoryStatus,
  ActionStatus,
  SessionStatus,
  EpisodeStatus,
  ContextOperation,
  AgentRelationType,
  Message,
  ShortMemory,
  MemoryItem,
  RecallResult,
  ExtractResult,
  MemoryPage,
  MemoryStats,
  ActionRecord,
  ActionPage,
  ToolStat,
  ActionStats,
  ContextEntry,
  ContextNamespace,
  ContextHistoryEntry,
  Agent,
  AgentPage,
  AgentRelation,
  AgentExportData,
  ImportResponse,
  Session,
  SessionPage,
  Episode,
  EpisodeDetail,
  EpisodePage,
  CrewLayerClientOptions,
} from "./types.js";

// Resource param types
export type {
  AppendParams,
  MessagesParams,
  RecallParams,
  ExtractParams,
  ListMemoriesParams,
  DeleteMemoryParams,
} from "./resources/memory.js";

export type {
  LogActionParams,
  ListActionsParams,
} from "./resources/actions.js";

export type {
  WriteContextParams,
  ReadContextParams,
  DeleteContextParams,
  ListNamespaceParams,
  ContextHistoryParams,
  RollbackContextParams,
  SubscribeParams,
} from "./resources/context.js";

export type {
  CreateAgentParams,
  UpdateAgentParams,
  ListAgentsParams,
  SetStatusParams,
  SetRelationParams,
} from "./resources/agents.js";

export type {
  CreateSessionParams,
  UpdateSessionParams,
  ListSessionsParams,
} from "./resources/sessions.js";

export type {
  CreateEpisodeParams,
  ListEpisodesParams,
  RecallEpisodeParams,
} from "./resources/episodes.js";
