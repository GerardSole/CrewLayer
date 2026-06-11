'use strict';

// src/errors.ts
var CrewLayerError = class extends Error {
  constructor(message, options) {
    super(message);
    this.name = "CrewLayerError";
    this.status = options?.status;
    this.body = options?.body;
  }
};
var AuthError = class extends CrewLayerError {
  constructor(message = "Unauthorized", options) {
    super(message, { status: options?.status ?? 401, body: options?.body });
    this.name = "AuthError";
  }
};
var NotFoundError = class extends CrewLayerError {
  constructor(message = "Not found", options) {
    super(message, { status: 404, body: options?.body });
    this.name = "NotFoundError";
  }
};
var ConflictError = class extends CrewLayerError {
  constructor(message = "Conflict", options) {
    super(message, { status: 409, body: options?.body });
    this.name = "ConflictError";
  }
};
var RateLimitError = class extends CrewLayerError {
  constructor(message = "Rate limit exceeded", options) {
    super(message, { status: 429, body: options?.body });
    this.name = "RateLimitError";
  }
};
var ServerError = class extends CrewLayerError {
  constructor(message = "Internal server error", options) {
    super(message, { status: options?.status ?? 500, body: options?.body });
    this.name = "ServerError";
  }
};
async function throwIfError(response) {
  if (response.ok) return;
  let body;
  try {
    body = await response.json();
  } catch {
    body = await response.text().catch(() => void 0);
  }
  const detail = typeof body === "object" && body !== null && "detail" in body ? String(body["detail"]) : `HTTP ${response.status}`;
  if (response.status === 401 || response.status === 403) {
    throw new AuthError(detail, { status: response.status, body });
  }
  if (response.status === 404) {
    throw new NotFoundError(detail, { body });
  }
  if (response.status === 409) {
    throw new ConflictError(detail, { body });
  }
  if (response.status === 429) {
    throw new RateLimitError(detail, { body });
  }
  if (response.status >= 500) {
    throw new ServerError(detail, { status: response.status, body });
  }
  throw new CrewLayerError(detail, { status: response.status, body });
}

// src/http.ts
var RETRY_ON = /* @__PURE__ */ new Set([500, 502, 503, 504]);
var MAX_RETRIES = 3;
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
var HttpClient = class {
  constructor(options) {
    this.baseUrl = options.baseUrl.replace(/\/$/, "");
    this.apiKey = options.apiKey;
    this.maxRetries = options.maxRetries ?? MAX_RETRIES;
    this.timeout = options.timeout ?? 3e4;
  }
  buildUrl(path, params) {
    const url = `${this.baseUrl}${path}`;
    if (!params) return url;
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== void 0 && v !== null) {
        qs.set(k, String(v));
      }
    }
    const str = qs.toString();
    return str ? `${url}?${str}` : url;
  }
  async request(method, path, options) {
    const url = this.buildUrl(path, options?.params);
    const headers = {
      "X-API-Key": this.apiKey
    };
    if (!options?.raw && options?.body !== void 0) {
      headers["Content-Type"] = "application/json";
    }
    const init = {
      method,
      headers
    };
    if (options?.body !== void 0) {
      init.body = JSON.stringify(options.body);
    }
    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      if (attempt > 0) {
        await sleep(2 ** (attempt - 1) * 1e3);
      }
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.timeout);
      const signal = options?.signal ? abortEither(options.signal, controller.signal) : controller.signal;
      try {
        const response = await fetch(url, { ...init, signal });
        clearTimeout(timer);
        if (RETRY_ON.has(response.status) && attempt < this.maxRetries) {
          continue;
        }
        await throwIfError(response);
        if (response.status === 204) return void 0;
        return await response.json();
      } catch (err) {
        clearTimeout(timer);
        const isAbort = err instanceof Error && err.name === "AbortError";
        if (isAbort || attempt >= this.maxRetries) {
          throw err;
        }
        if (!(err instanceof Error && "status" in err)) {
          continue;
        }
        throw err;
      }
    }
    throw new ServerError("Max retries exceeded");
  }
  /** Returns the raw Response for streaming (SSE). No retry. */
  async stream(path, options) {
    const url = this.buildUrl(path, options?.params);
    const response = await fetch(url, {
      method: "GET",
      headers: {
        "X-API-Key": this.apiKey,
        Accept: "text/event-stream"
      },
      signal: options?.signal
    });
    await throwIfError(response);
    return response;
  }
  get(path, options) {
    return this.request("GET", path, options);
  }
  post(path, body, options) {
    return this.request("POST", path, { ...options, body });
  }
  put(path, body, options) {
    return this.request("PUT", path, { ...options, body });
  }
  patch(path, body, options) {
    return this.request("PATCH", path, { ...options, body });
  }
  delete(path, options) {
    return this.request("DELETE", path, options);
  }
};
function abortEither(a, b) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (a.aborted || b.aborted) {
    controller.abort();
  } else {
    a.addEventListener("abort", abort, { once: true });
    b.addEventListener("abort", abort, { once: true });
  }
  return controller.signal;
}

// src/resources/memory.ts
var MemoryResource = class {
  constructor(http) {
    this.http = http;
  }
  /**
   * Append a message to the short-term memory for a session.
   * Messages are stored in Redis and feed into long-term extraction.
   */
  async append(params) {
    const { agentId, ...body } = params;
    return this.http.post(
      `/v1/agents/${agentId}/memory/messages`,
      {
        role: body.role,
        content: body.content,
        session_id: body.sessionId,
        metadata: body.metadata ?? {}
      }
    );
  }
  /** Retrieve the short-term message history for a session. */
  async messages(params) {
    return this.http.get(
      `/v1/agents/${params.agentId}/memory/messages`,
      { params: { session_id: params.sessionId } }
    );
  }
  /**
   * Semantic search over long-term memories using cosine similarity.
   * Returns memories sorted by relevance.
   */
  async recall(params) {
    const { agentId, query, limit, minSimilarity, sessionId, tags } = params;
    return this.http.post(
      `/v1/agents/${agentId}/memory/recall`,
      {
        query,
        limit,
        min_similarity: minSimilarity,
        session_id: sessionId,
        tags
      }
    );
  }
  /**
   * Extract and persist long-term memories from a session's message history.
   * Uses Claude to identify important facts, decisions and context.
   */
  async extract(params) {
    const { agentId, sessionId, minImportance } = params;
    return this.http.post(
      `/v1/agents/${agentId}/memory/extract`,
      { session_id: sessionId, min_importance: minImportance }
    );
  }
  /** List long-term memories with optional pagination and archived filter. */
  async list(params) {
    const { agentId, limit, page, includeArchived, tags } = params;
    return this.http.get(`/v1/agents/${agentId}/memory`, {
      params: {
        limit,
        page,
        include_archived: includeArchived,
        tags: tags?.join(",")
      }
    });
  }
  /** Get aggregate memory stats for an agent (counts, avg importance, etc.). */
  async stats(agentId) {
    return this.http.get(`/v1/agents/${agentId}/memory/stats`);
  }
  /** Hard-delete a single long-term memory entry. */
  async delete(params) {
    await this.http.delete(`/v1/agents/${params.agentId}/memory/${params.memoryId}`);
  }
};

// src/resources/actions.ts
var ActionsResource = class {
  constructor(http) {
    this.http = http;
  }
  /** Log a new action for an agent. */
  async log(params) {
    const { agentId, ...rest } = params;
    return this.http.post(`/v1/agents/${agentId}/actions`, {
      tool_name: rest.toolName,
      input_params: rest.inputParams ?? {},
      output_result: rest.outputResult ?? {},
      status: rest.status ?? "success",
      session_id: rest.sessionId,
      duration_ms: rest.durationMs,
      error_msg: rest.errorMsg,
      metadata: rest.metadata ?? {}
    });
  }
  /** Retrieve a specific action by ID. */
  async get(agentId, actionId) {
    return this.http.get(`/v1/agents/${agentId}/actions/${actionId}`);
  }
  /** List actions for an agent with optional filtering and cursor pagination. */
  async list(params) {
    const { agentId, status, toolName, limit, cursor, sessionId } = params;
    return this.http.get(`/v1/agents/${agentId}/actions`, {
      params: {
        status,
        tool_name: toolName,
        limit,
        cursor,
        session_id: sessionId
      }
    });
  }
  /** Get aggregated action statistics grouped by tool name. */
  async stats(agentId) {
    return this.http.get(`/v1/agents/${agentId}/actions/stats`);
  }
};

// src/streaming.ts
var SSEStream = class {
  constructor() {
    this._handlers = /* @__PURE__ */ new Map();
    this._controller = new AbortController();
  }
  get signal() {
    return this._controller.signal;
  }
  on(event, handler) {
    const list = this._handlers.get(event) ?? [];
    list.push(handler);
    this._handlers.set(event, list);
    return this;
  }
  off(event, handler) {
    const list = this._handlers.get(event) ?? [];
    this._handlers.set(event, list.filter((h) => h !== handler));
    return this;
  }
  /** Close the underlying SSE connection. */
  close() {
    this._controller.abort();
  }
  /** @internal */
  _emit(event, data) {
    const handlers = this._handlers.get(event) ?? [];
    for (const h of handlers) h(data);
  }
};
async function* parseSse(response) {
  if (!response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      let event = "message";
      let data = "";
      let id;
      for (const raw of lines) {
        const line = raw.trimEnd();
        if (line === "") {
          if (data !== "") {
            yield { event, data, id };
          }
          event = "message";
          data = "";
          id = void 0;
        } else if (line.startsWith("event:")) {
          event = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          data += (data ? "\n" : "") + line.slice(5).trim();
        } else if (line.startsWith("id:")) {
          id = line.slice(3).trim();
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
function openContextStream(url, apiKey) {
  const stream = new SSEStream();
  void (async () => {
    try {
      const response = await fetch(url, {
        headers: {
          "X-API-Key": apiKey,
          Accept: "text/event-stream"
        },
        signal: stream.signal
      });
      await throwIfError(response);
      for await (const { event, data } of parseSse(response)) {
        if (stream.signal.aborted) break;
        try {
          const parsed = JSON.parse(data);
          if (event === "updated") {
            stream._emit("updated", parsed);
          } else if (event === "deleted") {
            stream._emit("deleted", parsed);
          }
        } catch {
        }
      }
    } catch (err) {
      const isAbort = err instanceof Error && err.name === "AbortError";
      if (!isAbort) {
        stream._emit("error", err instanceof Error ? err : new Error(String(err)));
      }
    } finally {
      stream._emit("close", void 0);
    }
  })();
  return stream;
}

// src/resources/context.ts
var ContextResource = class {
  constructor(http) {
    this.http = http;
  }
  /**
   * Write (create or update) a context entry on the blackboard.
   * Supports optimistic locking via `expectedVersion`.
   */
  async write(params) {
    const { namespace, key, value, expectedVersion, writtenBy, expiresAt, propagate } = params;
    return this.http.put(`/v1/context/${namespace}/${key}`, {
      value,
      expected_version: expectedVersion,
      written_by: writtenBy,
      expires_at: expiresAt,
      propagate
    });
  }
  /** Read a single context entry. Throws NotFoundError if absent. */
  async read(params) {
    return this.http.get(`/v1/context/${params.namespace}/${params.key}`);
  }
  /** Delete a context entry from the blackboard. */
  async delete(params) {
    await this.http.delete(`/v1/context/${params.namespace}/${params.key}`);
  }
  /** List all entries in a namespace. */
  async listNamespace(params) {
    return this.http.get(`/v1/context/${params.namespace}`);
  }
  /** Retrieve the immutable write history for a context key. */
  async history(params) {
    const { namespace, key, limit, cursor } = params;
    return this.http.get(
      `/v1/context/${namespace}/${key}/history`,
      { params: { limit, cursor } }
    );
  }
  /** Retrieve the value of a key at a specific historical version. */
  async historyAt(params) {
    return this.http.get(
      `/v1/context/${params.namespace}/${params.key}/history/${params.version}`
    );
  }
  /** Roll a key back to a previous version, creating a rollback history entry. */
  async rollback(params) {
    return this.http.post(
      `/v1/context/${params.namespace}/${params.key}/rollback`,
      { version: params.version }
    );
  }
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
  subscribe(params) {
    const url = `${this.http.baseUrl}/v1/context/${params.namespace}/${params.key}/subscribe`;
    return openContextStream(url, this.http.apiKey);
  }
};

// src/resources/agents.ts
var AgentsResource = class {
  constructor(http) {
    this.http = http;
  }
  /** Create a new agent. */
  async create(params) {
    return this.http.post("/v1/agents", {
      name: params.name,
      description: params.description,
      config: params.config ?? {},
      tags: params.tags ?? []
    });
  }
  /** List agents with optional status/tags filter. */
  async list(params) {
    return this.http.get("/v1/agents", {
      params: {
        status: params?.status,
        tags: params?.tags?.join(","),
        limit: params?.limit,
        page: params?.page
      }
    });
  }
  /** Get a single agent by ID. */
  async get(agentId) {
    return this.http.get(`/v1/agents/${agentId}`);
  }
  /** Update agent fields. Partial updates are supported. */
  async update(agentId, params) {
    return this.http.patch(`/v1/agents/${agentId}`, {
      name: params.name,
      description: params.description,
      config: params.config,
      tags: params.tags
    });
  }
  /** Delete an agent and all associated data. */
  async delete(agentId) {
    await this.http.delete(`/v1/agents/${agentId}`);
  }
  /** Get the current status of an agent (cached in Redis for ~60s). */
  async getStatus(agentId) {
    return this.http.get(`/v1/agents/${agentId}/status`);
  }
  /** Update the operational status of an agent. */
  async setStatus(params) {
    return this.http.patch(`/v1/agents/${params.agentId}/status`, {
      status: params.status,
      session_id: params.sessionId
    });
  }
  /** Add one or more tags to an agent. */
  async addTags(agentId, tags) {
    return this.http.post(`/v1/agents/${agentId}/tags`, { tags });
  }
  /** Remove a single tag from an agent. */
  async removeTag(agentId, tag) {
    await this.http.delete(`/v1/agents/${agentId}/tags/${tag}`);
  }
  /** List available tags across all agents with their usage counts. */
  async listTags() {
    return this.http.get("/v1/agents/tags");
  }
  // ─── Relations ─────────────────────────────────────────────────────────────
  /** Create a directional relation between two agents. */
  async setRelation(params) {
    return this.http.post(`/v1/agents/${params.agentId}/relations`, {
      target_id: params.targetId,
      relation_type: params.relationType
    });
  }
  /** List all relations for an agent. */
  async listRelations(agentId) {
    return this.http.get(`/v1/agents/${agentId}/relations`);
  }
  /** Get the hierarchical tree of relations rooted at this agent. */
  async getTree(agentId) {
    return this.http.get(`/v1/agents/${agentId}/tree`);
  }
  /** Remove a relation between two agents (bidirectional). */
  async deleteRelation(agentId, otherId) {
    await this.http.delete(`/v1/agents/${agentId}/relations/${otherId}`);
  }
  // ─── Export / Import ───────────────────────────────────────────────────────
  /**
   * Export a full agent snapshot (memories, actions, episodes, sessions).
   * Returns the parsed export object. For large agents, prefer streaming
   * via the raw HTTP endpoint to avoid buffering everything in memory.
   */
  async export(agentId) {
    return this.http.get(`/v1/agents/${agentId}/export`);
  }
  /**
   * Import a previously exported agent. Creates a new agent with new IDs.
   * Returns the new agent, an id_map of old→new UUIDs, and any warnings.
   */
  async import(data) {
    return this.http.post("/v1/agents/import", data);
  }
};

// src/resources/sessions.ts
var SessionsResource = class {
  constructor(http) {
    this.http = http;
  }
  /** Start a new session for an agent. */
  async create(params) {
    return this.http.post("/v1/sessions", {
      agent_id: params.agentId,
      episode_id: params.episodeId,
      metadata: params.metadata ?? {}
    });
  }
  /** Get a session by ID. */
  async get(sessionId) {
    return this.http.get(`/v1/sessions/${sessionId}`);
  }
  /**
   * Close an active session.
   * This transitions the agent status back to idle.
   */
  async close(sessionId) {
    return this.http.post(`/v1/sessions/${sessionId}/close`);
  }
  /**
   * Update session metadata (e.g. assign or clear episode_id).
   */
  async update(params) {
    return this.http.patch(`/v1/sessions/${params.sessionId}`, {
      episode_id: params.episodeId
    });
  }
  /** List sessions, optionally filtered by agent or status. */
  async list(params) {
    return this.http.get("/v1/sessions", {
      params: {
        agent_id: params?.agentId,
        status: params?.status,
        limit: params?.limit,
        page: params?.page
      }
    });
  }
};

// src/resources/episodes.ts
var EpisodesResource = class {
  constructor(http) {
    this.http = http;
  }
  /** Create a new episode to group related sessions and memories. */
  async create(params) {
    const { agentId, ...rest } = params;
    return this.http.post(`/v1/agents/${agentId}/episodes`, {
      title: rest.title,
      description: rest.description,
      metadata: rest.metadata ?? {}
    });
  }
  /** List episodes for an agent, optionally filtered by status. */
  async list(params) {
    const { agentId, status, limit, page } = params;
    return this.http.get(`/v1/agents/${agentId}/episodes`, {
      params: { status, limit, page }
    });
  }
  /**
   * Get episode detail including linked sessions and memories.
   */
  async get(agentId, episodeId) {
    return this.http.get(`/v1/agents/${agentId}/episodes/${episodeId}`);
  }
  /**
   * Complete an episode. Triggers Claude to generate a summary of all
   * linked sessions and memories.
   */
  async complete(agentId, episodeId) {
    return this.http.post(`/v1/agents/${agentId}/episodes/${episodeId}/complete`);
  }
  /**
   * Semantic recall scoped to a single episode's memories.
   */
  async recall(params) {
    const { agentId, episodeId, query, limit, minSimilarity } = params;
    return this.http.post(
      `/v1/agents/${agentId}/episodes/${episodeId}/recall`,
      { query, limit, min_similarity: minSimilarity }
    );
  }
};

// src/client.ts
var DEFAULT_BASE_URL = "http://localhost:8000";
var CrewLayerClient = class {
  constructor(options = {}) {
    const apiKey = options.apiKey ?? (typeof process !== "undefined" ? process.env["CREWLAYER_API_KEY"] : void 0) ?? "";
    const baseUrl = options.baseUrl ?? DEFAULT_BASE_URL;
    this._http = new HttpClient({
      baseUrl,
      apiKey,
      maxRetries: options.maxRetries,
      timeout: options.timeout
    });
    this.memory = new MemoryResource(this._http);
    this.actions = new ActionsResource(this._http);
    this.context = new ContextResource(this._http);
    this.agents = new AgentsResource(this._http);
    this.sessions = new SessionsResource(this._http);
    this.episodes = new EpisodesResource(this._http);
  }
};

exports.ActionsResource = ActionsResource;
exports.AgentsResource = AgentsResource;
exports.AuthError = AuthError;
exports.ConflictError = ConflictError;
exports.ContextResource = ContextResource;
exports.CrewLayerClient = CrewLayerClient;
exports.CrewLayerError = CrewLayerError;
exports.EpisodesResource = EpisodesResource;
exports.MemoryResource = MemoryResource;
exports.NotFoundError = NotFoundError;
exports.RateLimitError = RateLimitError;
exports.SSEStream = SSEStream;
exports.ServerError = ServerError;
exports.SessionsResource = SessionsResource;
exports.openContextStream = openContextStream;
//# sourceMappingURL=index.js.map
//# sourceMappingURL=index.js.map