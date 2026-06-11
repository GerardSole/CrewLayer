// ─── Common ──────────────────────────────────────────────────────────────────

export type Role = "user" | "assistant" | "system" | "tool";
export type AgentStatus = "idle" | "working" | "error";
export type MemoryStatus = "active" | "archived";
export type ActionStatus = "success" | "error" | "running";
export type SessionStatus = "active" | "closed";
export type EpisodeStatus = "active" | "completed" | "archived";
export type ContextOperation = "created" | "updated" | "deleted" | "rollback";

// ─── Memory ──────────────────────────────────────────────────────────────────

export interface Message {
  role: Role;
  content: string;
  metadata: Record<string, unknown>;
}

export interface ShortMemory {
  sessionId: string;
  messages: Message[];
  count: number;
}

export interface MemoryItem {
  id: string;
  agentId: string;
  content: string;
  summary?: string;
  importance: number;
  tags: string[];
  status: MemoryStatus;
  accessCount: number;
  createdAt: string;
  updatedAt: string;
  sessionId?: string;
  /** Cosine similarity — only present on recall results. */
  similarity?: number;
}

export interface RecallResult {
  query: string;
  results: MemoryItem[];
}

export interface ExtractResult {
  extractedCount: number;
  memoryIds: string[];
}

export interface MemoryPage {
  items: MemoryItem[];
  total: number;
  page: number;
  pageSize: number;
}

export interface MemoryStats {
  agentId: string;
  totalMemories: number;
  activeMemories: number;
  archivedMemories: number;
  avgImportance: number;
}

// ─── Actions ─────────────────────────────────────────────────────────────────

export interface ActionRecord {
  id: string;
  tenantId: string;
  agentId: string;
  toolName: string;
  inputParams: Record<string, unknown>;
  outputResult: Record<string, unknown>;
  status: ActionStatus;
  timestamp: string;
  sessionId?: string;
  durationMs?: number;
  errorMsg?: string;
  metadata: Record<string, unknown>;
}

export interface ActionPage {
  items: ActionRecord[];
  count: number;
  nextCursor?: string;
}

export interface ToolStat {
  toolName: string;
  count: number;
  errorRate: number;
  avgDurationMs?: number;
}

export interface ActionStats {
  agentId: string;
  totalActions: number;
  errorRate: number;
  byTool: ToolStat[];
  avgDurationMs?: number;
}

// ─── Context ─────────────────────────────────────────────────────────────────

export interface ContextEntry {
  id: string;
  tenantId: string;
  namespace: string;
  key: string;
  value: Record<string, unknown>;
  version: number;
  createdAt: string;
  updatedAt: string;
  writtenBy?: string;
  expiresAt?: string;
}

export interface ContextNamespace {
  namespace: string;
  entries: ContextEntry[];
  count: number;
}

export interface ContextHistoryEntry {
  id: string;
  namespace: string;
  key: string;
  value?: Record<string, unknown>;
  version: number;
  operation: ContextOperation;
  writtenBy?: string;
  createdAt: string;
}

// ─── Agents ──────────────────────────────────────────────────────────────────

export interface Agent {
  id: string;
  tenantId: string;
  name: string;
  description?: string;
  config: Record<string, unknown>;
  status: AgentStatus;
  tags: string[];
  currentSessionId?: string;
  statusUpdatedAt: string;
  createdAt: string;
  updatedAt: string;
}

export interface AgentStatus_ {
  agentId: string;
  status: AgentStatus;
  currentSessionId?: string;
  statusUpdatedAt: string;
}

export interface AgentPage {
  items: Agent[];
  total: number;
  page: number;
  pageSize: number;
}

export type AgentRelationType = "supervisor" | "collaborator" | "delegate";

export interface AgentRelation {
  supervisorId: string;
  subordinateId: string;
  relationType: AgentRelationType;
  createdAt: string;
}

// ─── Sessions ────────────────────────────────────────────────────────────────

export interface Session {
  id: string;
  tenantId: string;
  agentId: string;
  status: SessionStatus;
  summary?: string;
  messageCount: number;
  startedAt: string;
  closedAt?: string;
  episodeId?: string;
  metadata: Record<string, unknown>;
}

export interface SessionPage {
  items: Session[];
  total: number;
}

// ─── Episodes ────────────────────────────────────────────────────────────────

export interface Episode {
  id: string;
  tenantId: string;
  agentId: string;
  title: string;
  description?: string;
  status: EpisodeStatus;
  summary?: string;
  startedAt: string;
  completedAt?: string;
  metadata: Record<string, unknown>;
}

export interface EpisodeDetail extends Episode {
  sessions: Session[];
  memories: MemoryItem[];
}

export interface EpisodePage {
  items: Episode[];
  total: number;
}

// ─── Export/Import ───────────────────────────────────────────────────────────

export interface AgentExportData {
  exportVersion: string;
  exportedAt: string;
  agent: Agent;
  memories: MemoryItem[];
  actions: ActionRecord[];
  episodes: Episode[];
  sessions: Session[];
  episodeMemories: Array<{ episodeId: string; memoryId: string }>;
  relations: AgentRelation[];
}

export interface ImportResponse {
  agent: Agent;
  idMap: Record<string, string>;
  warnings: string[];
}

// ─── Client config ───────────────────────────────────────────────────────────

export interface CrewLayerClientOptions {
  /** API key (crwl_...). Falls back to CREWLAYER_API_KEY env var in Node.js. */
  apiKey?: string;
  /** Base URL of the CrewLayer API. Defaults to http://localhost:8000. */
  baseUrl?: string;
  /** Maximum retry attempts on 5xx errors. Default: 3. */
  maxRetries?: number;
  /** Request timeout in milliseconds. Default: 30 000. */
  timeout?: number;
}
