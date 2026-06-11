interface RequestOptions {
    params?: Record<string, string | number | boolean | undefined | null>;
    body?: unknown;
    signal?: AbortSignal;
    /** Skip JSON Content-Type header (e.g. for streaming requests). */
    raw?: boolean;
}
declare class HttpClient {
    readonly baseUrl: string;
    readonly apiKey: string;
    private readonly maxRetries;
    private readonly timeout;
    constructor(options: {
        baseUrl: string;
        apiKey: string;
        maxRetries?: number;
        timeout?: number;
    });
    private buildUrl;
    request<T = unknown>(method: string, path: string, options?: RequestOptions): Promise<T>;
    /** Returns the raw Response for streaming (SSE). No retry. */
    stream(path: string, options?: Omit<RequestOptions, "body">): Promise<Response>;
    get<T = unknown>(path: string, options?: Omit<RequestOptions, "body">): Promise<T>;
    post<T = unknown>(path: string, body?: unknown, options?: Omit<RequestOptions, "body">): Promise<T>;
    put<T = unknown>(path: string, body?: unknown, options?: Omit<RequestOptions, "body">): Promise<T>;
    patch<T = unknown>(path: string, body?: unknown, options?: Omit<RequestOptions, "body">): Promise<T>;
    delete<T = unknown>(path: string, options?: Omit<RequestOptions, "body">): Promise<T>;
}

type Role = "user" | "assistant" | "system" | "tool";
type AgentStatus = "idle" | "working" | "error";
type MemoryStatus = "active" | "archived";
type ActionStatus = "success" | "error" | "running";
type SessionStatus = "active" | "closed";
type EpisodeStatus = "active" | "completed" | "archived";
type ContextOperation = "created" | "updated" | "deleted" | "rollback";
interface Message {
    role: Role;
    content: string;
    metadata: Record<string, unknown>;
}
interface ShortMemory {
    sessionId: string;
    messages: Message[];
    count: number;
}
interface MemoryItem {
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
interface RecallResult {
    query: string;
    results: MemoryItem[];
}
interface ExtractResult {
    extractedCount: number;
    memoryIds: string[];
}
interface MemoryPage {
    items: MemoryItem[];
    total: number;
    page: number;
    pageSize: number;
}
interface MemoryStats {
    agentId: string;
    totalMemories: number;
    activeMemories: number;
    archivedMemories: number;
    avgImportance: number;
}
interface ActionRecord {
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
interface ActionPage {
    items: ActionRecord[];
    count: number;
    nextCursor?: string;
}
interface ToolStat {
    toolName: string;
    count: number;
    errorRate: number;
    avgDurationMs?: number;
}
interface ActionStats {
    agentId: string;
    totalActions: number;
    errorRate: number;
    byTool: ToolStat[];
    avgDurationMs?: number;
}
interface ContextEntry {
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
interface ContextNamespace {
    namespace: string;
    entries: ContextEntry[];
    count: number;
}
interface ContextHistoryEntry {
    id: string;
    namespace: string;
    key: string;
    value?: Record<string, unknown>;
    version: number;
    operation: ContextOperation;
    writtenBy?: string;
    createdAt: string;
}
interface Agent {
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
interface AgentPage {
    items: Agent[];
    total: number;
    page: number;
    pageSize: number;
}
type AgentRelationType = "supervisor" | "collaborator" | "delegate";
interface AgentRelation {
    supervisorId: string;
    subordinateId: string;
    relationType: AgentRelationType;
    createdAt: string;
}
interface Session {
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
interface SessionPage {
    items: Session[];
    total: number;
}
interface Episode {
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
interface EpisodeDetail extends Episode {
    sessions: Session[];
    memories: MemoryItem[];
}
interface EpisodePage {
    items: Episode[];
    total: number;
}
interface AgentExportData {
    exportVersion: string;
    exportedAt: string;
    agent: Agent;
    memories: MemoryItem[];
    actions: ActionRecord[];
    episodes: Episode[];
    sessions: Session[];
    episodeMemories: Array<{
        episodeId: string;
        memoryId: string;
    }>;
    relations: AgentRelation[];
}
interface ImportResponse {
    agent: Agent;
    idMap: Record<string, string>;
    warnings: string[];
}
interface CrewLayerClientOptions {
    /** API key (crwl_...). Falls back to CREWLAYER_API_KEY env var in Node.js. */
    apiKey?: string;
    /** Base URL of the CrewLayer API. Defaults to http://localhost:8000. */
    baseUrl?: string;
    /** Maximum retry attempts on 5xx errors. Default: 3. */
    maxRetries?: number;
    /** Request timeout in milliseconds. Default: 30 000. */
    timeout?: number;
}

interface AppendParams {
    agentId: string;
    role: Role;
    content: string;
    sessionId?: string;
    metadata?: Record<string, unknown>;
}
interface MessagesParams {
    agentId: string;
    sessionId: string;
}
interface RecallParams {
    agentId: string;
    query: string;
    limit?: number;
    minSimilarity?: number;
    sessionId?: string;
    tags?: string[];
}
interface ExtractParams {
    agentId: string;
    sessionId: string;
    /** Minimum importance score (0–1) for extracted memories. */
    minImportance?: number;
}
interface ListMemoriesParams {
    agentId: string;
    limit?: number;
    page?: number;
    includeArchived?: boolean;
    tags?: string[];
}
interface DeleteMemoryParams {
    agentId: string;
    memoryId: string;
}
declare class MemoryResource {
    private readonly http;
    constructor(http: HttpClient);
    /**
     * Append a message to the short-term memory for a session.
     * Messages are stored in Redis and feed into long-term extraction.
     */
    append(params: AppendParams): Promise<ShortMemory>;
    /** Retrieve the short-term message history for a session. */
    messages(params: MessagesParams): Promise<ShortMemory>;
    /**
     * Semantic search over long-term memories using cosine similarity.
     * Returns memories sorted by relevance.
     */
    recall(params: RecallParams): Promise<RecallResult>;
    /**
     * Extract and persist long-term memories from a session's message history.
     * Uses Claude to identify important facts, decisions and context.
     */
    extract(params: ExtractParams): Promise<ExtractResult>;
    /** List long-term memories with optional pagination and archived filter. */
    list(params: ListMemoriesParams): Promise<MemoryPage>;
    /** Get aggregate memory stats for an agent (counts, avg importance, etc.). */
    stats(agentId: string): Promise<MemoryStats>;
    /** Hard-delete a single long-term memory entry. */
    delete(params: DeleteMemoryParams): Promise<void>;
}

interface LogActionParams {
    agentId: string;
    toolName: string;
    inputParams?: Record<string, unknown>;
    outputResult?: Record<string, unknown>;
    status?: ActionStatus;
    sessionId?: string;
    durationMs?: number;
    errorMsg?: string;
    metadata?: Record<string, unknown>;
}
interface ListActionsParams {
    agentId: string;
    status?: ActionStatus;
    toolName?: string;
    limit?: number;
    cursor?: string;
    sessionId?: string;
}
declare class ActionsResource {
    private readonly http;
    constructor(http: HttpClient);
    /** Log a new action for an agent. */
    log(params: LogActionParams): Promise<ActionRecord>;
    /** Retrieve a specific action by ID. */
    get(agentId: string, actionId: string): Promise<ActionRecord>;
    /** List actions for an agent with optional filtering and cursor pagination. */
    list(params: ListActionsParams): Promise<ActionPage>;
    /** Get aggregated action statistics grouped by tool name. */
    stats(agentId: string): Promise<ActionStats>;
}

type Listener<T> = (data: T) => void;
/** Minimal cross-platform EventEmitter for SSE streams. */
declare class SSEStream<Events extends Record<string, any>> {
    private readonly _handlers;
    private readonly _controller;
    get signal(): AbortSignal;
    on<K extends keyof Events & string>(event: K, handler: Listener<Events[K]>): this;
    off<K extends keyof Events & string>(event: K, handler: Listener<Events[K]>): this;
    /** Close the underlying SSE connection. */
    close(): void;
    /** @internal */
    _emit<K extends keyof Events & string>(event: K, data: Events[K]): void;
}
interface ContextStreamEvents {
    updated: ContextEntry;
    deleted: {
        key: string;
    };
    error: Error;
    close: undefined;
}
type ContextSSEStream = SSEStream<ContextStreamEvents>;
/**
 * Opens an SSE connection to the CrewLayer context subscribe endpoint and
 * returns a typed stream. The connection runs in the background — call
 * `stream.close()` to stop it.
 */
declare function openContextStream(url: string, apiKey: string): ContextSSEStream;

interface WriteContextParams {
    namespace: string;
    key: string;
    value: Record<string, unknown>;
    /** Pass the current version to enforce optimistic locking (409 on mismatch). */
    expectedVersion?: number;
    writtenBy?: string;
    /** ISO-8601 datetime string for TTL-based expiry. */
    expiresAt?: string;
    /** Propagate write to supervisor/subordinate agents. */
    propagate?: boolean;
}
interface ReadContextParams {
    namespace: string;
    key: string;
}
interface DeleteContextParams {
    namespace: string;
    key: string;
}
interface ListNamespaceParams {
    namespace: string;
}
interface ContextHistoryParams {
    namespace: string;
    key: string;
    limit?: number;
    cursor?: string;
}
interface RollbackContextParams {
    namespace: string;
    key: string;
    version: number;
}
interface SubscribeParams {
    namespace: string;
    key: string;
}
declare class ContextResource {
    private readonly http;
    constructor(http: HttpClient);
    /**
     * Write (create or update) a context entry on the blackboard.
     * Supports optimistic locking via `expectedVersion`.
     */
    write(params: WriteContextParams): Promise<ContextEntry>;
    /** Read a single context entry. Throws NotFoundError if absent. */
    read(params: ReadContextParams): Promise<ContextEntry>;
    /** Delete a context entry from the blackboard. */
    delete(params: DeleteContextParams): Promise<void>;
    /** List all entries in a namespace. */
    listNamespace(params: ListNamespaceParams): Promise<ContextNamespace>;
    /** Retrieve the immutable write history for a context key. */
    history(params: ContextHistoryParams): Promise<ContextHistoryEntry[]>;
    /** Retrieve the value of a key at a specific historical version. */
    historyAt(params: {
        namespace: string;
        key: string;
        version: number;
    }): Promise<ContextHistoryEntry>;
    /** Roll a key back to a previous version, creating a rollback history entry. */
    rollback(params: RollbackContextParams): Promise<ContextEntry>;
    /**
     * Subscribe to real-time updates for a context key via SSE.
     *
     * @example
     * const stream = client.context.subscribe({ namespace: "proj:abc", key: "status" })
     * stream.on("updated", (entry) => console.log(entry.value))
     * stream.on("deleted", ({ key }) => console.log("deleted", key))
     * // later:
     * stream.close()
     */
    subscribe(params: SubscribeParams): ContextSSEStream;
}

interface CreateAgentParams {
    name: string;
    description?: string;
    config?: Record<string, unknown>;
    tags?: string[];
}
interface UpdateAgentParams {
    name?: string;
    description?: string;
    config?: Record<string, unknown>;
    tags?: string[];
}
interface ListAgentsParams {
    status?: AgentStatus;
    tags?: string[];
    limit?: number;
    page?: number;
}
interface SetStatusParams {
    agentId: string;
    status: AgentStatus;
    sessionId?: string;
}
interface SetRelationParams {
    agentId: string;
    targetId: string;
    relationType: AgentRelationType;
}
declare class AgentsResource {
    private readonly http;
    constructor(http: HttpClient);
    /** Create a new agent. */
    create(params: CreateAgentParams): Promise<Agent>;
    /** List agents with optional status/tags filter. */
    list(params?: ListAgentsParams): Promise<AgentPage>;
    /** Get a single agent by ID. */
    get(agentId: string): Promise<Agent>;
    /** Update agent fields. Partial updates are supported. */
    update(agentId: string, params: UpdateAgentParams): Promise<Agent>;
    /** Delete an agent and all associated data. */
    delete(agentId: string): Promise<void>;
    /** Get the current status of an agent (cached in Redis for ~60s). */
    getStatus(agentId: string): Promise<{
        agentId: string;
        status: AgentStatus;
        currentSessionId?: string;
        statusUpdatedAt: string;
    }>;
    /** Update the operational status of an agent. */
    setStatus(params: SetStatusParams): Promise<Agent>;
    /** Add one or more tags to an agent. */
    addTags(agentId: string, tags: string[]): Promise<Agent>;
    /** Remove a single tag from an agent. */
    removeTag(agentId: string, tag: string): Promise<void>;
    /** List available tags across all agents with their usage counts. */
    listTags(): Promise<Array<{
        tag: string;
        count: number;
    }>>;
    /** Create a directional relation between two agents. */
    setRelation(params: SetRelationParams): Promise<AgentRelation>;
    /** List all relations for an agent. */
    listRelations(agentId: string): Promise<AgentRelation[]>;
    /** Get the hierarchical tree of relations rooted at this agent. */
    getTree(agentId: string): Promise<unknown>;
    /** Remove a relation between two agents (bidirectional). */
    deleteRelation(agentId: string, otherId: string): Promise<void>;
    /**
     * Export a full agent snapshot (memories, actions, episodes, sessions).
     * Returns the parsed export object. For large agents, prefer streaming
     * via the raw HTTP endpoint to avoid buffering everything in memory.
     */
    export(agentId: string): Promise<AgentExportData>;
    /**
     * Import a previously exported agent. Creates a new agent with new IDs.
     * Returns the new agent, an id_map of old→new UUIDs, and any warnings.
     */
    import(data: AgentExportData): Promise<ImportResponse>;
}

interface CreateSessionParams {
    agentId: string;
    episodeId?: string;
    metadata?: Record<string, unknown>;
}
interface UpdateSessionParams {
    sessionId: string;
    episodeId?: string | null;
}
interface ListSessionsParams {
    agentId?: string;
    status?: "active" | "closed";
    limit?: number;
    page?: number;
}
declare class SessionsResource {
    private readonly http;
    constructor(http: HttpClient);
    /** Start a new session for an agent. */
    create(params: CreateSessionParams): Promise<Session>;
    /** Get a session by ID. */
    get(sessionId: string): Promise<Session>;
    /**
     * Close an active session.
     * This transitions the agent status back to idle.
     */
    close(sessionId: string): Promise<Session>;
    /**
     * Update session metadata (e.g. assign or clear episode_id).
     */
    update(params: UpdateSessionParams): Promise<Session>;
    /** List sessions, optionally filtered by agent or status. */
    list(params?: ListSessionsParams): Promise<SessionPage>;
}

interface CreateEpisodeParams {
    agentId: string;
    title: string;
    description?: string;
    metadata?: Record<string, unknown>;
}
interface ListEpisodesParams {
    agentId: string;
    status?: EpisodeStatus;
    limit?: number;
    page?: number;
}
interface RecallEpisodeParams {
    agentId: string;
    episodeId: string;
    query: string;
    limit?: number;
    minSimilarity?: number;
}
declare class EpisodesResource {
    private readonly http;
    constructor(http: HttpClient);
    /** Create a new episode to group related sessions and memories. */
    create(params: CreateEpisodeParams): Promise<Episode>;
    /** List episodes for an agent, optionally filtered by status. */
    list(params: ListEpisodesParams): Promise<EpisodePage>;
    /**
     * Get episode detail including linked sessions and memories.
     */
    get(agentId: string, episodeId: string): Promise<EpisodeDetail>;
    /**
     * Complete an episode. Triggers Claude to generate a summary of all
     * linked sessions and memories.
     */
    complete(agentId: string, episodeId: string): Promise<Episode>;
    /**
     * Semantic recall scoped to a single episode's memories.
     */
    recall(params: RecallEpisodeParams): Promise<MemoryItem[]>;
}

declare class CrewLayerClient {
    readonly memory: MemoryResource;
    readonly actions: ActionsResource;
    readonly context: ContextResource;
    readonly agents: AgentsResource;
    readonly sessions: SessionsResource;
    readonly episodes: EpisodesResource;
    /** @internal */
    readonly _http: HttpClient;
    constructor(options?: CrewLayerClientOptions);
}

declare class CrewLayerError extends Error {
    readonly status: number | undefined;
    readonly body: unknown;
    constructor(message: string, options?: {
        status?: number;
        body?: unknown;
    });
}
declare class AuthError extends CrewLayerError {
    constructor(message?: string, options?: {
        status?: number;
        body?: unknown;
    });
}
declare class NotFoundError extends CrewLayerError {
    constructor(message?: string, options?: {
        body?: unknown;
    });
}
declare class ConflictError extends CrewLayerError {
    constructor(message?: string, options?: {
        body?: unknown;
    });
}
declare class RateLimitError extends CrewLayerError {
    constructor(message?: string, options?: {
        body?: unknown;
    });
}
declare class ServerError extends CrewLayerError {
    constructor(message?: string, options?: {
        status?: number;
        body?: unknown;
    });
}

export { type ActionPage, type ActionRecord, type ActionStats, type ActionStatus, ActionsResource, type Agent, type AgentExportData, type AgentPage, type AgentRelation, type AgentRelationType, type AgentStatus, AgentsResource, type AppendParams, AuthError, ConflictError, type ContextEntry, type ContextHistoryEntry, type ContextHistoryParams, type ContextNamespace, type ContextOperation, ContextResource, type ContextSSEStream, type ContextStreamEvents, type CreateAgentParams, type CreateEpisodeParams, type CreateSessionParams, CrewLayerClient, type CrewLayerClientOptions, CrewLayerError, type DeleteContextParams, type DeleteMemoryParams, type Episode, type EpisodeDetail, type EpisodePage, type EpisodeStatus, EpisodesResource, type ExtractParams, type ExtractResult, type ImportResponse, type ListActionsParams, type ListAgentsParams, type ListEpisodesParams, type ListMemoriesParams, type ListNamespaceParams, type ListSessionsParams, type LogActionParams, type MemoryItem, type MemoryPage, MemoryResource, type MemoryStats, type MemoryStatus, type Message, type MessagesParams, NotFoundError, RateLimitError, type ReadContextParams, type RecallEpisodeParams, type RecallParams, type RecallResult, type Role, type RollbackContextParams, SSEStream, ServerError, type Session, type SessionPage, type SessionStatus, SessionsResource, type SetRelationParams, type SetStatusParams, type ShortMemory, type SubscribeParams, type ToolStat, type UpdateAgentParams, type UpdateSessionParams, type WriteContextParams, openContextStream };
