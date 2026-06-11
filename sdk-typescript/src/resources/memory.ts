import type { HttpClient } from "../http.js";
import type {
  ShortMemory,
  MemoryItem,
  RecallResult,
  ExtractResult,
  MemoryPage,
  MemoryStats,
  Role,
} from "../types.js";

export interface AppendParams {
  agentId: string;
  role: Role;
  content: string;
  sessionId?: string;
  metadata?: Record<string, unknown>;
}

export interface MessagesParams {
  agentId: string;
  sessionId: string;
}

export interface RecallParams {
  agentId: string;
  query: string;
  limit?: number;
  minSimilarity?: number;
  sessionId?: string;
  tags?: string[];
}

export interface ExtractParams {
  agentId: string;
  sessionId: string;
  /** Minimum importance score (0–1) for extracted memories. */
  minImportance?: number;
}

export interface ListMemoriesParams {
  agentId: string;
  limit?: number;
  page?: number;
  includeArchived?: boolean;
  tags?: string[];
}

export interface DeleteMemoryParams {
  agentId: string;
  memoryId: string;
}

export class MemoryResource {
  constructor(private readonly http: HttpClient) {}

  /**
   * Append a message to the short-term memory for a session.
   * Messages are stored in Redis and feed into long-term extraction.
   */
  async append(params: AppendParams): Promise<ShortMemory> {
    const { agentId, ...body } = params;
    return this.http.post<ShortMemory>(
      `/v1/agents/${agentId}/memory/messages`,
      {
        role: body.role,
        content: body.content,
        session_id: body.sessionId,
        metadata: body.metadata ?? {},
      }
    );
  }

  /** Retrieve the short-term message history for a session. */
  async messages(params: MessagesParams): Promise<ShortMemory> {
    return this.http.get<ShortMemory>(
      `/v1/agents/${params.agentId}/memory/messages`,
      { params: { session_id: params.sessionId } }
    );
  }

  /**
   * Semantic search over long-term memories using cosine similarity.
   * Returns memories sorted by relevance.
   */
  async recall(params: RecallParams): Promise<RecallResult> {
    const { agentId, query, limit, minSimilarity, sessionId, tags } = params;
    return this.http.post<RecallResult>(
      `/v1/agents/${agentId}/memory/recall`,
      {
        query,
        limit,
        min_similarity: minSimilarity,
        session_id: sessionId,
        tags,
      }
    );
  }

  /**
   * Extract and persist long-term memories from a session's message history.
   * Uses Claude to identify important facts, decisions and context.
   */
  async extract(params: ExtractParams): Promise<ExtractResult> {
    const { agentId, sessionId, minImportance } = params;
    return this.http.post<ExtractResult>(
      `/v1/agents/${agentId}/memory/extract`,
      { session_id: sessionId, min_importance: minImportance }
    );
  }

  /** List long-term memories with optional pagination and archived filter. */
  async list(params: ListMemoriesParams): Promise<MemoryPage> {
    const { agentId, limit, page, includeArchived, tags } = params;
    return this.http.get<MemoryPage>(`/v1/agents/${agentId}/memory`, {
      params: {
        limit,
        page,
        include_archived: includeArchived,
        tags: tags?.join(","),
      },
    });
  }

  /** Get aggregate memory stats for an agent (counts, avg importance, etc.). */
  async stats(agentId: string): Promise<MemoryStats> {
    return this.http.get<MemoryStats>(`/v1/agents/${agentId}/memory/stats`);
  }

  /** Hard-delete a single long-term memory entry. */
  async delete(params: DeleteMemoryParams): Promise<void> {
    await this.http.delete(`/v1/agents/${params.agentId}/memory/${params.memoryId}`);
  }
}
