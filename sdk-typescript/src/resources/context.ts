import type { HttpClient } from "../http.js";
import type { ContextEntry, ContextNamespace, ContextHistoryEntry } from "../types.js";
import { openContextStream, type ContextSSEStream } from "../streaming.js";

export interface WriteContextParams {
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

export interface ReadContextParams {
  namespace: string;
  key: string;
}

export interface DeleteContextParams {
  namespace: string;
  key: string;
}

export interface ListNamespaceParams {
  namespace: string;
}

export interface ContextHistoryParams {
  namespace: string;
  key: string;
  limit?: number;
  cursor?: string;
}

export interface RollbackContextParams {
  namespace: string;
  key: string;
  version: number;
}

export interface SubscribeParams {
  namespace: string;
  key: string;
}

export class ContextResource {
  constructor(private readonly http: HttpClient) {}

  /**
   * Write (create or update) a context entry on the blackboard.
   * Supports optimistic locking via `expectedVersion`.
   */
  async write(params: WriteContextParams): Promise<ContextEntry> {
    const { namespace, key, value, expectedVersion, writtenBy, expiresAt, propagate } = params;
    return this.http.put<ContextEntry>(`/v1/context/${namespace}/${key}`, {
      value,
      expected_version: expectedVersion,
      written_by: writtenBy,
      expires_at: expiresAt,
      propagate,
    });
  }

  /** Read a single context entry. Throws NotFoundError if absent. */
  async read(params: ReadContextParams): Promise<ContextEntry> {
    return this.http.get<ContextEntry>(`/v1/context/${params.namespace}/${params.key}`);
  }

  /** Delete a context entry from the blackboard. */
  async delete(params: DeleteContextParams): Promise<void> {
    await this.http.delete(`/v1/context/${params.namespace}/${params.key}`);
  }

  /** List all entries in a namespace. */
  async listNamespace(params: ListNamespaceParams): Promise<ContextNamespace> {
    return this.http.get<ContextNamespace>(`/v1/context/${params.namespace}`);
  }

  /** Retrieve the immutable write history for a context key. */
  async history(params: ContextHistoryParams): Promise<ContextHistoryEntry[]> {
    const { namespace, key, limit, cursor } = params;
    return this.http.get<ContextHistoryEntry[]>(
      `/v1/context/${namespace}/${key}/history`,
      { params: { limit, cursor } }
    );
  }

  /** Retrieve the value of a key at a specific historical version. */
  async historyAt(params: { namespace: string; key: string; version: number }): Promise<ContextHistoryEntry> {
    return this.http.get<ContextHistoryEntry>(
      `/v1/context/${params.namespace}/${params.key}/history/${params.version}`
    );
  }

  /** Roll a key back to a previous version, creating a rollback history entry. */
  async rollback(params: RollbackContextParams): Promise<ContextEntry> {
    return this.http.post<ContextEntry>(
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
  subscribe(params: SubscribeParams): ContextSSEStream {
    const url = `${this.http.baseUrl}/v1/context/${params.namespace}/${params.key}/subscribe`;
    return openContextStream(url, this.http.apiKey);
  }
}
