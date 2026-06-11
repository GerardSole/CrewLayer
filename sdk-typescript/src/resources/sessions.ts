import type { HttpClient } from "../http.js";
import type { Session, SessionPage } from "../types.js";

export interface CreateSessionParams {
  agentId: string;
  episodeId?: string;
  metadata?: Record<string, unknown>;
}

export interface UpdateSessionParams {
  sessionId: string;
  episodeId?: string | null;
}

export interface ListSessionsParams {
  agentId?: string;
  status?: "active" | "closed";
  limit?: number;
  page?: number;
}

export class SessionsResource {
  constructor(private readonly http: HttpClient) {}

  /** Start a new session for an agent. */
  async create(params: CreateSessionParams): Promise<Session> {
    return this.http.post<Session>("/v1/sessions", {
      agent_id: params.agentId,
      episode_id: params.episodeId,
      metadata: params.metadata ?? {},
    });
  }

  /** Get a session by ID. */
  async get(sessionId: string): Promise<Session> {
    return this.http.get<Session>(`/v1/sessions/${sessionId}`);
  }

  /**
   * Close an active session.
   * This transitions the agent status back to idle.
   */
  async close(sessionId: string): Promise<Session> {
    return this.http.post<Session>(`/v1/sessions/${sessionId}/close`);
  }

  /**
   * Update session metadata (e.g. assign or clear episode_id).
   */
  async update(params: UpdateSessionParams): Promise<Session> {
    return this.http.patch<Session>(`/v1/sessions/${params.sessionId}`, {
      episode_id: params.episodeId,
    });
  }

  /** List sessions, optionally filtered by agent or status. */
  async list(params?: ListSessionsParams): Promise<SessionPage> {
    return this.http.get<SessionPage>("/v1/sessions", {
      params: {
        agent_id: params?.agentId,
        status: params?.status,
        limit: params?.limit,
        page: params?.page,
      },
    });
  }
}
