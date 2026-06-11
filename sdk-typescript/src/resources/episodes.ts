import type { HttpClient } from "../http.js";
import type { Episode, EpisodeDetail, EpisodePage, MemoryItem, EpisodeStatus } from "../types.js";

export interface CreateEpisodeParams {
  agentId: string;
  title: string;
  description?: string;
  metadata?: Record<string, unknown>;
}

export interface ListEpisodesParams {
  agentId: string;
  status?: EpisodeStatus;
  limit?: number;
  page?: number;
}

export interface RecallEpisodeParams {
  agentId: string;
  episodeId: string;
  query: string;
  limit?: number;
  minSimilarity?: number;
}

export class EpisodesResource {
  constructor(private readonly http: HttpClient) {}

  /** Create a new episode to group related sessions and memories. */
  async create(params: CreateEpisodeParams): Promise<Episode> {
    const { agentId, ...rest } = params;
    return this.http.post<Episode>(`/v1/agents/${agentId}/episodes`, {
      title: rest.title,
      description: rest.description,
      metadata: rest.metadata ?? {},
    });
  }

  /** List episodes for an agent, optionally filtered by status. */
  async list(params: ListEpisodesParams): Promise<EpisodePage> {
    const { agentId, status, limit, page } = params;
    return this.http.get<EpisodePage>(`/v1/agents/${agentId}/episodes`, {
      params: { status, limit, page },
    });
  }

  /**
   * Get episode detail including linked sessions and memories.
   */
  async get(agentId: string, episodeId: string): Promise<EpisodeDetail> {
    return this.http.get<EpisodeDetail>(`/v1/agents/${agentId}/episodes/${episodeId}`);
  }

  /**
   * Complete an episode. Triggers Claude to generate a summary of all
   * linked sessions and memories.
   */
  async complete(agentId: string, episodeId: string): Promise<Episode> {
    return this.http.post<Episode>(`/v1/agents/${agentId}/episodes/${episodeId}/complete`);
  }

  /**
   * Semantic recall scoped to a single episode's memories.
   */
  async recall(params: RecallEpisodeParams): Promise<MemoryItem[]> {
    const { agentId, episodeId, query, limit, minSimilarity } = params;
    return this.http.post<MemoryItem[]>(
      `/v1/agents/${agentId}/episodes/${episodeId}/recall`,
      { query, limit, min_similarity: minSimilarity }
    );
  }
}
