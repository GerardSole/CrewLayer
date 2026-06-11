import type { HttpClient } from "../http.js";
import type {
  Agent,
  AgentPage,
  AgentStatus,
  AgentRelation,
  AgentRelationType,
  AgentExportData,
  ImportResponse,
} from "../types.js";

export interface CreateAgentParams {
  name: string;
  description?: string;
  config?: Record<string, unknown>;
  tags?: string[];
}

export interface UpdateAgentParams {
  name?: string;
  description?: string;
  config?: Record<string, unknown>;
  tags?: string[];
}

export interface ListAgentsParams {
  status?: AgentStatus;
  tags?: string[];
  limit?: number;
  page?: number;
}

export interface SetStatusParams {
  agentId: string;
  status: AgentStatus;
  sessionId?: string;
}

export interface SetRelationParams {
  agentId: string;
  targetId: string;
  relationType: AgentRelationType;
}

export class AgentsResource {
  constructor(private readonly http: HttpClient) {}

  /** Create a new agent. */
  async create(params: CreateAgentParams): Promise<Agent> {
    return this.http.post<Agent>("/v1/agents", {
      name: params.name,
      description: params.description,
      config: params.config ?? {},
      tags: params.tags ?? [],
    });
  }

  /** List agents with optional status/tags filter. */
  async list(params?: ListAgentsParams): Promise<AgentPage> {
    return this.http.get<AgentPage>("/v1/agents", {
      params: {
        status: params?.status,
        tags: params?.tags?.join(","),
        limit: params?.limit,
        page: params?.page,
      },
    });
  }

  /** Get a single agent by ID. */
  async get(agentId: string): Promise<Agent> {
    return this.http.get<Agent>(`/v1/agents/${agentId}`);
  }

  /** Update agent fields. Partial updates are supported. */
  async update(agentId: string, params: UpdateAgentParams): Promise<Agent> {
    return this.http.patch<Agent>(`/v1/agents/${agentId}`, {
      name: params.name,
      description: params.description,
      config: params.config,
      tags: params.tags,
    });
  }

  /** Delete an agent and all associated data. */
  async delete(agentId: string): Promise<void> {
    await this.http.delete(`/v1/agents/${agentId}`);
  }

  /** Get the current status of an agent (cached in Redis for ~60s). */
  async getStatus(agentId: string): Promise<{ agentId: string; status: AgentStatus; currentSessionId?: string; statusUpdatedAt: string }> {
    return this.http.get(`/v1/agents/${agentId}/status`);
  }

  /** Update the operational status of an agent. */
  async setStatus(params: SetStatusParams): Promise<Agent> {
    return this.http.patch<Agent>(`/v1/agents/${params.agentId}/status`, {
      status: params.status,
      session_id: params.sessionId,
    });
  }

  /** Add one or more tags to an agent. */
  async addTags(agentId: string, tags: string[]): Promise<Agent> {
    return this.http.post<Agent>(`/v1/agents/${agentId}/tags`, { tags });
  }

  /** Remove a single tag from an agent. */
  async removeTag(agentId: string, tag: string): Promise<void> {
    await this.http.delete(`/v1/agents/${agentId}/tags/${tag}`);
  }

  /** List available tags across all agents with their usage counts. */
  async listTags(): Promise<Array<{ tag: string; count: number }>> {
    return this.http.get("/v1/agents/tags");
  }

  // ─── Relations ─────────────────────────────────────────────────────────────

  /** Create a directional relation between two agents. */
  async setRelation(params: SetRelationParams): Promise<AgentRelation> {
    return this.http.post<AgentRelation>(`/v1/agents/${params.agentId}/relations`, {
      target_id: params.targetId,
      relation_type: params.relationType,
    });
  }

  /** List all relations for an agent. */
  async listRelations(agentId: string): Promise<AgentRelation[]> {
    return this.http.get<AgentRelation[]>(`/v1/agents/${agentId}/relations`);
  }

  /** Get the hierarchical tree of relations rooted at this agent. */
  async getTree(agentId: string): Promise<unknown> {
    return this.http.get(`/v1/agents/${agentId}/tree`);
  }

  /** Remove a relation between two agents (bidirectional). */
  async deleteRelation(agentId: string, otherId: string): Promise<void> {
    await this.http.delete(`/v1/agents/${agentId}/relations/${otherId}`);
  }

  // ─── Export / Import ───────────────────────────────────────────────────────

  /**
   * Export a full agent snapshot (memories, actions, episodes, sessions).
   * Returns the parsed export object. For large agents, prefer streaming
   * via the raw HTTP endpoint to avoid buffering everything in memory.
   */
  async export(agentId: string): Promise<AgentExportData> {
    return this.http.get<AgentExportData>(`/v1/agents/${agentId}/export`);
  }

  /**
   * Import a previously exported agent. Creates a new agent with new IDs.
   * Returns the new agent, an id_map of old→new UUIDs, and any warnings.
   */
  async import(data: AgentExportData): Promise<ImportResponse> {
    return this.http.post<ImportResponse>("/v1/agents/import", data);
  }
}
