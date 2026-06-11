/**
 * Vercel AI SDK integration for the CrewLayer TypeScript SDK.
 *
 * Three adapters for building AI-powered Next.js / Vercel apps:
 *
 * - `crewLayerMemory()` — memory provider compatible with Vercel AI SDK's
 *   `useChat` and `streamText` memory interface
 * - `crewLayerTools()` — tool set exposing recall, log, read/write context
 *   directly to the LLM as callable tools
 * - `CrewLayerDataStream` — wraps any `AsyncIterable<string>` text stream
 *   and automatically logs it as an action in CrewLayer on completion
 *
 * No hard dependency on the `ai` package — all types are duck-typed so the
 * integration works with any version of the Vercel AI SDK >= 3.0.
 *
 * @example
 * ```ts
 * // app/api/chat/route.ts
 * import { streamText } from "ai";
 * import { anthropic } from "@ai-sdk/anthropic";
 * import { CrewLayerClient } from "crewlayer";
 * import {
 *   crewLayerMemory,
 *   crewLayerTools,
 *   CrewLayerDataStream,
 * } from "crewlayer/integrations/vercel-ai";
 *
 * const client = new CrewLayerClient({ apiKey: process.env.CREWLAYER_API_KEY! });
 * const memory = crewLayerMemory({ client, agentId: "agent-001" });
 * const tools = crewLayerTools({ client, agentId: "agent-001" });
 *
 * export async function POST(req: Request) {
 *   const { messages } = await req.json();
 *   const contextMessages = await memory.get(messages);
 *
 *   const result = streamText({
 *     model: anthropic("claude-opus-4-8"),
 *     messages: [...contextMessages, ...messages],
 *     tools,
 *   });
 *
 *   await memory.update({ messages });
 *   return new CrewLayerDataStream(result.textStream, { client, agentId: "agent-001" }).toResponse();
 * }
 * ```
 */

import type { CrewLayerClient } from "../client.js";

// ---------------------------------------------------------------------------
// Minimal duck-type interfaces — no hard dep on "ai" package
// ---------------------------------------------------------------------------

/** Minimal subset of Vercel AI SDK's CoreMessage (duck-typed). */
export interface VercelCoreMessage {
  role: "user" | "assistant" | "system" | "tool";
  content: string | VercelContentPart[];
}

export interface VercelContentPart {
  type: string;
  text?: string;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Internal JSON Schema types (no Zod or ai imports needed)
// ---------------------------------------------------------------------------

interface JsonSchemaProp {
  type: string;
  description?: string;
  enum?: string[];
  minimum?: number;
  maximum?: number;
}

interface JsonSchemaObject {
  type: "object";
  properties: Record<string, JsonSchemaProp>;
  required?: string[];
  additionalProperties?: boolean;
}

// ---------------------------------------------------------------------------
// Options
// ---------------------------------------------------------------------------

export interface CrewLayerMemoryOptions {
  /** A `CrewLayerClient` instance. */
  client: CrewLayerClient;
  /** Target agent UUID in CrewLayer. */
  agentId: string;
  /** Session key for short-term memory (default: `"default"`). */
  sessionId?: string;
  /**
   * Maximum number of short-term messages returned by `getMessages`.
   * The most-recent N messages are returned (default: 20).
   */
  messageLimit?: number;
  /**
   * Maximum number of long-term memories prepended as context by `get`.
   * Default: 5.
   */
  memoryLimit?: number;
}

export interface CrewLayerToolsOptions {
  /** A `CrewLayerClient` instance. */
  client: CrewLayerClient;
  /** Target agent UUID in CrewLayer. */
  agentId: string;
  /** Session key forwarded to recall and log calls (optional). */
  sessionId?: string;
}

export interface CrewLayerDataStreamOptions {
  /** A `CrewLayerClient` instance. */
  client: CrewLayerClient;
  /** Target agent UUID in CrewLayer. */
  agentId: string;
  /** Session key for the logged action (optional). */
  sessionId?: string;
  /** Tool name stored in the action record (default: `"vercel.stream"`). */
  toolName?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function extractText(content: VercelCoreMessage["content"]): string {
  if (typeof content === "string") return content;
  return content
    .filter((p): p is VercelContentPart & { text: string } =>
      p.type === "text" && typeof p.text === "string"
    )
    .map((p) => p.text)
    .join(" ")
    .trim();
}

function normaliseRole(role: string): VercelCoreMessage["role"] {
  if (role === "user" || role === "assistant" || role === "system" || role === "tool") {
    return role;
  }
  return "user"; // "human" and any unknown role → "user"
}

// ---------------------------------------------------------------------------
// crewLayerMemory
// ---------------------------------------------------------------------------

export interface CrewLayerMemoryProvider {
  /**
   * Called before each LLM invocation.
   * Extracts the last user message as a semantic query, recalls relevant
   * long-term memories, and returns them as a system message to prepend to
   * the conversation. Returns `[]` if there are no user messages or no recall
   * results.
   */
  get(messages: VercelCoreMessage[]): Promise<VercelCoreMessage[]>;

  /**
   * Called after each LLM completion.
   * Persists every non-system message in the provided array to CrewLayer
   * short-term memory. Never throws — errors are silently swallowed.
   */
  update(result: { messages: VercelCoreMessage[] }): Promise<void>;

  /**
   * Fetch the current session message history from CrewLayer and return it
   * as `VercelCoreMessage[]` so it can be passed directly to `streamText`.
   * Accepts an optional per-call `sessionId` override.
   */
  getMessages(params?: { sessionId?: string }): Promise<VercelCoreMessage[]>;

  /**
   * Append an array of messages to CrewLayer short-term memory.
   * Accepts an optional per-call `sessionId` override.
   * Never throws — errors are silently swallowed.
   */
  saveMessages(params: { messages: VercelCoreMessage[]; sessionId?: string }): Promise<void>;
}

/**
 * Create a memory provider compatible with the Vercel AI SDK memory interface.
 *
 * @example
 * ```ts
 * const memory = crewLayerMemory({ client, agentId: "agent-001", memoryLimit: 8 });
 *
 * // In your route handler:
 * const contextMessages = await memory.get(incomingMessages);
 * const result = streamText({ messages: [...contextMessages, ...incomingMessages] });
 * await memory.update({ messages: incomingMessages });
 * ```
 */
export function crewLayerMemory(options: CrewLayerMemoryOptions): CrewLayerMemoryProvider {
  const {
    client,
    agentId,
    sessionId = "default",
    memoryLimit = 5,
    messageLimit = 20,
  } = options;

  return {
    async get(messages) {
      const userMessages = messages.filter((m) => m.role === "user");
      if (userMessages.length === 0) return [];

      const query = extractText(userMessages[userMessages.length - 1].content);
      if (!query) return [];

      let recalled: Awaited<ReturnType<CrewLayerClient["memory"]["recall"]>>;
      try {
        recalled = await client.memory.recall({ agentId, query, limit: memoryLimit, sessionId });
      } catch {
        return [];
      }

      if (!recalled.results || recalled.results.length === 0) return [];

      const memoryText =
        "Relevant memories:\n" +
        recalled.results.map((m) => `- ${m.content}`).join("\n");

      return [{ role: "system", content: memoryText }];
    },

    async update({ messages }) {
      for (const msg of messages) {
        if (msg.role === "system") continue;
        const content = extractText(msg.content);
        if (!content) continue;
        try {
          await client.memory.append({
            agentId,
            role: msg.role as "user" | "assistant",
            content,
            sessionId,
          });
        } catch {
          // Never block the AI pipeline
        }
      }
    },

    async getMessages(params) {
      const sid = params?.sessionId ?? sessionId;
      let mem: Awaited<ReturnType<CrewLayerClient["memory"]["messages"]>>;
      try {
        mem = await client.memory.messages({ agentId, sessionId: sid });
      } catch {
        return [];
      }
      return (mem.messages ?? [])
        .slice(-messageLimit)
        .map((m) => ({
          role: normaliseRole(m.role),
          content: m.content,
        }));
    },

    async saveMessages({ messages, sessionId: callSid }) {
      const effectiveSid = callSid ?? sessionId;
      for (const msg of messages) {
        if (msg.role === "system") continue;
        const content = extractText(msg.content);
        if (!content) continue;
        try {
          await client.memory.append({
            agentId,
            role: msg.role as "user" | "assistant",
            content,
            sessionId: effectiveSid,
          });
        } catch {
          // Never block
        }
      }
    },
  };
}

// ---------------------------------------------------------------------------
// crewLayerTools
// ---------------------------------------------------------------------------

/** A single Vercel AI SDK-compatible tool definition. */
export interface CrewLayerTool<
  TArgs extends Record<string, unknown>,
  TResult,
> {
  description: string;
  parameters: JsonSchemaObject;
  execute(args: TArgs): Promise<TResult>;
}

export interface CrewLayerToolSet {
  recall_memory: CrewLayerTool<
    { query: string; limit?: number },
    Array<{ content: string; similarity: number; tags?: string[]; importance?: number }>
  >;
  log_action: CrewLayerTool<
    { toolName: string; status?: string; inputSummary?: string },
    { id: string; logged: boolean }
  >;
  read_context: CrewLayerTool<
    { namespace: string; key: string },
    { value: Record<string, unknown>; version: number }
  >;
  write_context: CrewLayerTool<
    { namespace: string; key: string; value: string },
    { version: number; written: boolean }
  >;
}

/**
 * Create a set of CrewLayer tools that an LLM can call during a `streamText`
 * or `generateText` invocation.
 *
 * Each tool's `parameters` follows the JSON Schema object format accepted by
 * the Vercel AI SDK (wrap with `jsonSchema()` helper if needed).
 *
 * @example
 * ```ts
 * import { jsonSchema } from "ai"; // only needed to satisfy strict types
 * const tools = crewLayerTools({ client, agentId: "agent-001" });
 *
 * streamText({
 *   model: anthropic("claude-opus-4-8"),
 *   messages,
 *   tools: {
 *     recall_memory: { ...tools.recall_memory, parameters: jsonSchema(tools.recall_memory.parameters) },
 *     write_context: { ...tools.write_context, parameters: jsonSchema(tools.write_context.parameters) },
 *   },
 * });
 * ```
 */
export function crewLayerTools(options: CrewLayerToolsOptions): CrewLayerToolSet {
  const { client, agentId, sessionId } = options;

  return {
    recall_memory: {
      description:
        "Recall semantically relevant long-term memories for this agent. " +
        "Use when you need context from past interactions or stored knowledge.",
      parameters: {
        type: "object",
        properties: {
          query: {
            type: "string",
            description: "What to search for in the agent's long-term memory.",
          },
          limit: {
            type: "integer",
            description: "Maximum number of memories to return (default: 5, max: 20).",
            minimum: 1,
            maximum: 20,
          },
        },
        required: ["query"],
        additionalProperties: false,
      },
      async execute({ query, limit = 5 }) {
        const result = await client.memory.recall({ agentId, query, limit, sessionId });
        return (result.results ?? []).map((m) => ({
          content: m.content,
          similarity: m.similarity,
          tags: m.tags,
          importance: m.importance,
        }));
      },
    },

    log_action: {
      description:
        "Log an action or tool usage to the CrewLayer audit trail. " +
        "Use to record important operations, decisions, or outcomes.",
      parameters: {
        type: "object",
        properties: {
          toolName: {
            type: "string",
            description: "Name of the tool or action being recorded (e.g. 'web_search').",
          },
          status: {
            type: "string",
            description: 'Outcome: "success" or "error".',
            enum: ["success", "error"],
          },
          inputSummary: {
            type: "string",
            description: "Short description of what the action did or what was passed as input.",
          },
        },
        required: ["toolName"],
        additionalProperties: false,
      },
      async execute({ toolName, status = "success", inputSummary = "" }) {
        const record = await client.actions.log({
          agentId,
          toolName,
          status: status as "success" | "error",
          inputParams: { summary: inputSummary },
          sessionId,
        });
        return { id: record.id, logged: true };
      },
    },

    read_context: {
      description:
        "Read a value from the shared CrewLayer blackboard. " +
        "Use to access shared state, coordination data, or values written by other agents.",
      parameters: {
        type: "object",
        properties: {
          namespace: {
            type: "string",
            description: "Blackboard namespace, e.g. 'project:abc' or 'team:dev'.",
          },
          key: {
            type: "string",
            description: "Key to read within the namespace.",
          },
        },
        required: ["namespace", "key"],
        additionalProperties: false,
      },
      async execute({ namespace, key }) {
        const entry = await client.context.read({ namespace, key });
        return { value: entry.value, version: entry.version };
      },
    },

    write_context: {
      description:
        "Write a value to the shared CrewLayer blackboard. " +
        "Use to persist shared state or coordinate with other agents. " +
        'The value must be a JSON-encoded object string, e.g. \'{"status":"done"}\'.',
      parameters: {
        type: "object",
        properties: {
          namespace: {
            type: "string",
            description: "Blackboard namespace, e.g. 'project:abc'.",
          },
          key: {
            type: "string",
            description: "Key to write within the namespace.",
          },
          value: {
            type: "string",
            description:
              "JSON-encoded object to write, e.g. '{\"done\": true}'. " +
              "Must be a JSON object (not a primitive or array).",
          },
        },
        required: ["namespace", "key", "value"],
        additionalProperties: false,
      },
      async execute({ namespace, key, value }) {
        let parsed: Record<string, unknown>;
        try {
          const candidate = JSON.parse(value) as unknown;
          parsed =
            typeof candidate === "object" &&
            candidate !== null &&
            !Array.isArray(candidate)
              ? (candidate as Record<string, unknown>)
              : { text: value };
        } catch {
          parsed = { text: value };
        }
        const entry = await client.context.write({ namespace, key, value: parsed });
        return { version: entry.version, written: true };
      },
    },
  };
}

// ---------------------------------------------------------------------------
// CrewLayerDataStream
// ---------------------------------------------------------------------------

/**
 * Wraps any `AsyncIterable<string>` text stream (e.g. Vercel AI SDK's
 * `result.textStream`) and automatically logs a `vercel.stream` action in
 * CrewLayer when the stream completes or errors.
 *
 * Implements `AsyncIterable<string>` so it can be used anywhere a standard
 * async iterable is expected. Use `toResponse()` to get a streaming
 * `Response` for Next.js route handlers.
 *
 * @example
 * ```ts
 * // app/api/chat/route.ts
 * export async function POST(req: Request) {
 *   const { messages } = await req.json();
 *   const result = streamText({ model: anthropic("claude-opus-4-8"), messages });
 *
 *   return new CrewLayerDataStream(result.textStream, {
 *     client,
 *     agentId: "agent-001",
 *     sessionId: "sess-001",
 *   }).toResponse();
 * }
 * ```
 */
export class CrewLayerDataStream implements AsyncIterable<string> {
  private readonly _source: AsyncIterable<string>;
  private readonly _client: CrewLayerClient;
  private readonly _agentId: string;
  private readonly _sessionId: string | undefined;
  private readonly _toolName: string;

  constructor(source: AsyncIterable<string>, options: CrewLayerDataStreamOptions) {
    this._source = source;
    this._client = options.client;
    this._agentId = options.agentId;
    this._sessionId = options.sessionId;
    this._toolName = options.toolName ?? "vercel.stream";
  }

  async *[Symbol.asyncIterator](): AsyncGenerator<string> {
    const startMs = Date.now();
    const chunks: string[] = [];
    let hasError = false;
    let errorMsg: string | undefined;

    try {
      for await (const chunk of this._source) {
        chunks.push(chunk);
        yield chunk;
      }
    } catch (err) {
      hasError = true;
      errorMsg = err instanceof Error ? err.message : String(err);
      throw err;
    } finally {
      const durationMs = Date.now() - startMs;
      const fullText = chunks.join("").slice(0, 2000);
      try {
        await this._client.actions.log({
          agentId: this._agentId,
          toolName: this._toolName,
          inputParams: {},
          outputResult: { text: fullText },
          status: hasError ? "error" : "success",
          sessionId: this._sessionId,
          durationMs,
          errorMsg,
        });
      } catch {
        // Never interrupt stream flow on log failure
      }
    }
  }

  /**
   * Convert this stream into a standard `Response` suitable for returning
   * directly from a Next.js / Vercel Edge route handler.
   *
   * Content-Type is `text/plain; charset=utf-8`.
   * Chunked transfer encoding is set automatically.
   */
  toResponse(init?: ResponseInit): Response {
    const encoder = new TextEncoder();
    const self = this; // eslint-disable-line @typescript-eslint/no-this-alias
    const body = new ReadableStream<Uint8Array>({
      async start(controller) {
        try {
          for await (const chunk of self) {
            controller.enqueue(encoder.encode(chunk));
          }
          controller.close();
        } catch (err) {
          controller.error(err);
        }
      },
    });

    const headers = new Headers({
      "Content-Type": "text/plain; charset=utf-8",
      "Transfer-Encoding": "chunked",
    });

    const extra = init?.headers;
    if (extra) {
      const src = extra instanceof Headers ? extra : new Headers(extra as HeadersInit);
      src.forEach((v, k) => headers.set(k, v));
    }

    return new Response(body, {
      status: init?.status ?? 200,
      statusText: init?.statusText,
      headers,
    });
  }
}
