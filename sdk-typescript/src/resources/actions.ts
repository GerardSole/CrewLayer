import type { HttpClient } from "../http.js";
import type { ActionRecord, ActionPage, ActionStats, ActionStatus } from "../types.js";

export interface LogActionParams {
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

export interface ListActionsParams {
  agentId: string;
  status?: ActionStatus;
  toolName?: string;
  limit?: number;
  cursor?: string;
  sessionId?: string;
}

export class ActionsResource {
  constructor(private readonly http: HttpClient) {}

  /** Log a new action for an agent. */
  async log(params: LogActionParams): Promise<ActionRecord> {
    const { agentId, ...rest } = params;
    return this.http.post<ActionRecord>(`/v1/agents/${agentId}/actions`, {
      tool_name: rest.toolName,
      input_params: rest.inputParams ?? {},
      output_result: rest.outputResult ?? {},
      status: rest.status ?? "success",
      session_id: rest.sessionId,
      duration_ms: rest.durationMs,
      error_msg: rest.errorMsg,
      metadata: rest.metadata ?? {},
    });
  }

  /** Retrieve a specific action by ID. */
  async get(agentId: string, actionId: string): Promise<ActionRecord> {
    return this.http.get<ActionRecord>(`/v1/agents/${agentId}/actions/${actionId}`);
  }

  /** List actions for an agent with optional filtering and cursor pagination. */
  async list(params: ListActionsParams): Promise<ActionPage> {
    const { agentId, status, toolName, limit, cursor, sessionId } = params;
    return this.http.get<ActionPage>(`/v1/agents/${agentId}/actions`, {
      params: {
        status,
        tool_name: toolName,
        limit,
        cursor,
        session_id: sessionId,
      },
    });
  }

  /** Get aggregated action statistics grouped by tool name. */
  async stats(agentId: string): Promise<ActionStats> {
    return this.http.get<ActionStats>(`/v1/agents/${agentId}/actions/stats`);
  }
}
