import type { ContextEntry } from "./types.js";
import { throwIfError } from "./errors.js";

type Listener<T> = (data: T) => void;

/** Minimal cross-platform EventEmitter for SSE streams. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export class SSEStream<Events extends Record<string, any>> {
  private readonly _handlers = new Map<string, Listener<unknown>[]>();
  private readonly _controller = new AbortController();

  get signal(): AbortSignal {
    return this._controller.signal;
  }

  on<K extends keyof Events & string>(event: K, handler: Listener<Events[K]>): this {
    const list = this._handlers.get(event) ?? [];
    list.push(handler as Listener<unknown>);
    this._handlers.set(event, list);
    return this;
  }

  off<K extends keyof Events & string>(event: K, handler: Listener<Events[K]>): this {
    const list = this._handlers.get(event) ?? [];
    this._handlers.set(event, list.filter((h) => h !== handler));
    return this;
  }

  /** Close the underlying SSE connection. */
  close(): void {
    this._controller.abort();
  }

  /** @internal */
  _emit<K extends keyof Events & string>(event: K, data: Events[K]): void {
    const handlers = this._handlers.get(event) ?? [];
    for (const h of handlers) h(data);
  }
}

// ─── SSE parser ──────────────────────────────────────────────────────────────

interface SSEEvent {
  event: string;
  data: string;
  id?: string;
}

async function* parseSse(response: Response): AsyncGenerator<SSEEvent> {
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
      let id: string | undefined;

      for (const raw of lines) {
        const line = raw.trimEnd();
        if (line === "") {
          if (data !== "") {
            yield { event, data, id };
          }
          event = "message";
          data = "";
          id = undefined;
        } else if (line.startsWith("event:")) {
          event = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          data += (data ? "\n" : "") + line.slice(5).trim();
        } else if (line.startsWith("id:")) {
          id = line.slice(3).trim();
        }
        // retry: and comment lines are ignored
      }
    }
  } finally {
    reader.releaseLock();
  }
}

// ─── Context SSE stream ───────────────────────────────────────────────────────

export interface ContextStreamEvents {
  updated: ContextEntry;
  deleted: { key: string };
  error: Error;
  close: undefined;
}

export type ContextSSEStream = SSEStream<ContextStreamEvents>;

/**
 * Opens an SSE connection to the CrewLayer context subscribe endpoint and
 * returns a typed stream. The connection runs in the background — call
 * `stream.close()` to stop it.
 */
export function openContextStream(
  url: string,
  apiKey: string
): ContextSSEStream {
  const stream = new SSEStream<ContextStreamEvents>();

  void (async () => {
    try {
      const response = await fetch(url, {
        headers: {
          "X-API-Key": apiKey,
          Accept: "text/event-stream",
        },
        signal: stream.signal,
      });

      await throwIfError(response);

      for await (const { event, data } of parseSse(response)) {
        if (stream.signal.aborted) break;
        try {
          const parsed: unknown = JSON.parse(data);
          if (event === "updated") {
            stream._emit("updated", parsed as ContextEntry);
          } else if (event === "deleted") {
            stream._emit("deleted", parsed as { key: string });
          }
        } catch {
          // ignore malformed events
        }
      }
    } catch (err) {
      const isAbort = err instanceof Error && err.name === "AbortError";
      if (!isAbort) {
        stream._emit("error", err instanceof Error ? err : new Error(String(err)));
      }
    } finally {
      stream._emit("close", undefined);
    }
  })();

  return stream;
}
