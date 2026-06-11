import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  crewLayerMemory,
  crewLayerTools,
  CrewLayerDataStream,
} from "../src/integrations/vercel-ai.js";
import type {
  VercelCoreMessage,
  CrewLayerMemoryOptions,
} from "../src/integrations/vercel-ai.js";
import type { CrewLayerClient } from "../src/client.js";

// ---------------------------------------------------------------------------
// Mock client factory
// ---------------------------------------------------------------------------

function makeMockClient(): CrewLayerClient {
  return {
    memory: {
      recall: vi.fn().mockResolvedValue({ query: "", results: [] }),
      messages: vi.fn().mockResolvedValue({ sessionId: "default", messages: [], count: 0 }),
      append: vi.fn().mockResolvedValue({ sessionId: "default", messages: [], count: 1 }),
    },
    actions: {
      log: vi.fn().mockResolvedValue({ id: "act-1", toolName: "test", status: "success" }),
    },
    context: {
      read: vi.fn().mockResolvedValue({
        id: "ctx-1",
        tenantId: "t1",
        namespace: "ns",
        key: "k",
        value: { hello: "world" },
        version: 1,
        createdAt: "",
        updatedAt: "",
      }),
      write: vi.fn().mockResolvedValue({
        id: "ctx-2",
        tenantId: "t1",
        namespace: "ns",
        key: "k",
        value: { hello: "world" },
        version: 2,
        createdAt: "",
        updatedAt: "",
      }),
    },
  } as unknown as CrewLayerClient;
}

// ---------------------------------------------------------------------------
// Async generator helpers for stream tests
// ---------------------------------------------------------------------------

async function* textSource(chunks: string[]): AsyncGenerator<string> {
  for (const chunk of chunks) {
    yield chunk;
  }
}

async function* failingSource(
  chunks: string[],
  failAfter: number,
): AsyncGenerator<string> {
  for (let i = 0; i < failAfter; i++) {
    yield chunks[i];
  }
  throw new Error("stream failure");
}

// ---------------------------------------------------------------------------
// crewLayerMemory
// ---------------------------------------------------------------------------

describe("crewLayerMemory", () => {
  let client: CrewLayerClient;

  beforeEach(() => {
    client = makeMockClient();
  });

  // ── get() ─────────────────────────────────────────────────────────────────

  describe("get()", () => {
    it("calls recall with the last user message as query", async () => {
      const memory = crewLayerMemory({ client, agentId: "ag-1" });
      const messages: VercelCoreMessage[] = [
        { role: "user", content: "Hello" },
        { role: "assistant", content: "Hi!" },
        { role: "user", content: "What is my name?" },
      ];
      await memory.get(messages);
      expect(client.memory.recall).toHaveBeenCalledWith(
        expect.objectContaining({ agentId: "ag-1", query: "What is my name?" }),
      );
    });

    it("returns recalled memories as a single system message", async () => {
      (client.memory.recall as ReturnType<typeof vi.fn>).mockResolvedValue({
        query: "test",
        results: [
          { content: "User prefers dark mode", similarity: 0.9, tags: [], importance: 0.8 },
          { content: "User is a TypeScript developer", similarity: 0.85, tags: [], importance: 0.7 },
        ],
      });
      const memory = crewLayerMemory({ client, agentId: "ag-1" });
      const result = await memory.get([{ role: "user", content: "Help me" }]);
      expect(result).toHaveLength(1);
      expect(result[0].role).toBe("system");
      expect(result[0].content).toContain("User prefers dark mode");
      expect(result[0].content).toContain("User is a TypeScript developer");
    });

    it("returns empty array when no user messages are present", async () => {
      const memory = crewLayerMemory({ client, agentId: "ag-1" });
      const result = await memory.get([{ role: "assistant", content: "Hi" }]);
      expect(result).toEqual([]);
      expect(client.memory.recall).not.toHaveBeenCalled();
    });

    it("returns empty array when recall returns no results", async () => {
      (client.memory.recall as ReturnType<typeof vi.fn>).mockResolvedValue({ query: "q", results: [] });
      const memory = crewLayerMemory({ client, agentId: "ag-1" });
      const result = await memory.get([{ role: "user", content: "Hello" }]);
      expect(result).toEqual([]);
    });

    it("uses the configured memoryLimit", async () => {
      const memory = crewLayerMemory({ client, agentId: "ag-1", memoryLimit: 3 });
      await memory.get([{ role: "user", content: "test" }]);
      expect(client.memory.recall).toHaveBeenCalledWith(
        expect.objectContaining({ limit: 3 }),
      );
    });

    it("uses default sessionId when none is provided", async () => {
      const memory = crewLayerMemory({ client, agentId: "ag-1" });
      await memory.get([{ role: "user", content: "test" }]);
      expect(client.memory.recall).toHaveBeenCalledWith(
        expect.objectContaining({ sessionId: "default" }),
      );
    });

    it("uses the configured sessionId", async () => {
      const memory = crewLayerMemory({ client, agentId: "ag-1", sessionId: "sess-42" });
      await memory.get([{ role: "user", content: "test" }]);
      expect(client.memory.recall).toHaveBeenCalledWith(
        expect.objectContaining({ sessionId: "sess-42" }),
      );
    });

    it("extracts text from array-based content parts", async () => {
      const memory = crewLayerMemory({ client, agentId: "ag-1" });
      await memory.get([
        { role: "user", content: [{ type: "text", text: "hello world" }] },
      ]);
      expect(client.memory.recall).toHaveBeenCalledWith(
        expect.objectContaining({ query: "hello world" }),
      );
    });

    it("returns empty array if recall throws", async () => {
      (client.memory.recall as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("network error"));
      const memory = crewLayerMemory({ client, agentId: "ag-1" });
      const result = await memory.get([{ role: "user", content: "test" }]);
      expect(result).toEqual([]);
    });

    it("returns empty array when messages array is empty", async () => {
      const memory = crewLayerMemory({ client, agentId: "ag-1" });
      const result = await memory.get([]);
      expect(result).toEqual([]);
    });
  });

  // ── update() ──────────────────────────────────────────────────────────────

  describe("update()", () => {
    it("appends each non-system message to CrewLayer", async () => {
      const memory = crewLayerMemory({ client, agentId: "ag-1" });
      await memory.update({
        messages: [
          { role: "user", content: "Hello" },
          { role: "assistant", content: "Hi!" },
          { role: "system", content: "You are helpful." },
        ],
      });
      expect(client.memory.append).toHaveBeenCalledTimes(2);
    });

    it("skips system messages entirely", async () => {
      const memory = crewLayerMemory({ client, agentId: "ag-1" });
      await memory.update({ messages: [{ role: "system", content: "System prompt" }] });
      expect(client.memory.append).not.toHaveBeenCalled();
    });

    it("passes the configured sessionId to append", async () => {
      const memory = crewLayerMemory({ client, agentId: "ag-1", sessionId: "sess-99" });
      await memory.update({ messages: [{ role: "user", content: "test" }] });
      expect(client.memory.append).toHaveBeenCalledWith(
        expect.objectContaining({ sessionId: "sess-99" }),
      );
    });

    it("handles empty messages array without errors", async () => {
      const memory = crewLayerMemory({ client, agentId: "ag-1" });
      await expect(memory.update({ messages: [] })).resolves.toBeUndefined();
      expect(client.memory.append).not.toHaveBeenCalled();
    });

    it("does not throw if append fails", async () => {
      (client.memory.append as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("fail"));
      const memory = crewLayerMemory({ client, agentId: "ag-1" });
      await expect(
        memory.update({ messages: [{ role: "user", content: "hi" }] }),
      ).resolves.toBeUndefined();
    });
  });

  // ── getMessages() ─────────────────────────────────────────────────────────

  describe("getMessages()", () => {
    it("calls memory.messages with the configured agentId and sessionId", async () => {
      const memory = crewLayerMemory({ client, agentId: "ag-1", sessionId: "s1" });
      await memory.getMessages();
      expect(client.memory.messages).toHaveBeenCalledWith({ agentId: "ag-1", sessionId: "s1" });
    });

    it("allows overriding sessionId per call", async () => {
      const memory = crewLayerMemory({ client, agentId: "ag-1" });
      await memory.getMessages({ sessionId: "override" });
      expect(client.memory.messages).toHaveBeenCalledWith({ agentId: "ag-1", sessionId: "override" });
    });

    it("returns empty array if messages resource fails", async () => {
      (client.memory.messages as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("fail"));
      const memory = crewLayerMemory({ client, agentId: "ag-1" });
      const result = await memory.getMessages();
      expect(result).toEqual([]);
    });

    it("normalises 'human' role to 'user'", async () => {
      (client.memory.messages as ReturnType<typeof vi.fn>).mockResolvedValue({
        sessionId: "default",
        messages: [{ role: "human", content: "Hello", id: "1", createdAt: "" }],
        count: 1,
      });
      const memory = crewLayerMemory({ client, agentId: "ag-1" });
      const msgs = await memory.getMessages();
      expect(msgs[0].role).toBe("user");
    });

    it("respects messageLimit by returning only the last N messages", async () => {
      (client.memory.messages as ReturnType<typeof vi.fn>).mockResolvedValue({
        sessionId: "default",
        messages: Array.from({ length: 30 }, (_, i) => ({
          role: "user",
          content: `msg ${i}`,
          id: String(i),
          createdAt: "",
        })),
        count: 30,
      });
      const memory = crewLayerMemory({ client, agentId: "ag-1", messageLimit: 5 });
      const msgs = await memory.getMessages();
      expect(msgs).toHaveLength(5);
      expect(msgs[0].content).toBe("msg 25");
    });
  });

  // ── saveMessages() ────────────────────────────────────────────────────────

  describe("saveMessages()", () => {
    it("appends each message to CrewLayer", async () => {
      const memory = crewLayerMemory({ client, agentId: "ag-1" });
      await memory.saveMessages({
        messages: [
          { role: "user", content: "hi" },
          { role: "assistant", content: "hello" },
        ],
      });
      expect(client.memory.append).toHaveBeenCalledTimes(2);
    });

    it("uses the per-call sessionId over the default", async () => {
      const memory = crewLayerMemory({ client, agentId: "ag-1", sessionId: "default" });
      await memory.saveMessages({
        messages: [{ role: "user", content: "test" }],
        sessionId: "custom",
      });
      expect(client.memory.append).toHaveBeenCalledWith(
        expect.objectContaining({ sessionId: "custom" }),
      );
    });

    it("skips system messages", async () => {
      const memory = crewLayerMemory({ client, agentId: "ag-1" });
      await memory.saveMessages({ messages: [{ role: "system", content: "system" }] });
      expect(client.memory.append).not.toHaveBeenCalled();
    });
  });
});

// ---------------------------------------------------------------------------
// crewLayerTools
// ---------------------------------------------------------------------------

describe("crewLayerTools", () => {
  let client: CrewLayerClient;

  beforeEach(() => {
    client = makeMockClient();
  });

  it("returns an object with four tools", () => {
    const tools = crewLayerTools({ client, agentId: "ag-1" });
    expect(Object.keys(tools).sort()).toEqual(
      ["log_action", "read_context", "recall_memory", "write_context"],
    );
  });

  it("each tool has description, parameters (type: 'object'), and execute", () => {
    const tools = crewLayerTools({ client, agentId: "ag-1" });
    for (const tool of Object.values(tools)) {
      expect(typeof tool.description).toBe("string");
      expect(tool.description.length).toBeGreaterThan(0);
      expect(tool.parameters.type).toBe("object");
      expect(typeof tool.execute).toBe("function");
    }
  });

  // ── recall_memory ─────────────────────────────────────────────────────────

  describe("recall_memory", () => {
    it("calls client.memory.recall with query and agentId", async () => {
      const tools = crewLayerTools({ client, agentId: "ag-1" });
      await tools.recall_memory.execute({ query: "my preferences" });
      expect(client.memory.recall).toHaveBeenCalledWith(
        expect.objectContaining({ agentId: "ag-1", query: "my preferences" }),
      );
    });

    it("uses a custom limit", async () => {
      const tools = crewLayerTools({ client, agentId: "ag-1" });
      await tools.recall_memory.execute({ query: "test", limit: 10 });
      expect(client.memory.recall).toHaveBeenCalledWith(
        expect.objectContaining({ limit: 10 }),
      );
    });

    it("defaults limit to 5", async () => {
      const tools = crewLayerTools({ client, agentId: "ag-1" });
      await tools.recall_memory.execute({ query: "test" });
      expect(client.memory.recall).toHaveBeenCalledWith(
        expect.objectContaining({ limit: 5 }),
      );
    });

    it("returns mapped memory items", async () => {
      (client.memory.recall as ReturnType<typeof vi.fn>).mockResolvedValue({
        query: "test",
        results: [
          { content: "I like TypeScript", similarity: 0.9, tags: ["pref"], importance: 0.8 },
        ],
      });
      const tools = crewLayerTools({ client, agentId: "ag-1" });
      const result = await tools.recall_memory.execute({ query: "preferences" });
      expect(result).toHaveLength(1);
      expect(result[0].content).toBe("I like TypeScript");
      expect(result[0].similarity).toBe(0.9);
      expect(result[0].tags).toEqual(["pref"]);
    });

    it("forwards sessionId from options", async () => {
      const tools = crewLayerTools({ client, agentId: "ag-1", sessionId: "s-x" });
      await tools.recall_memory.execute({ query: "q" });
      expect(client.memory.recall).toHaveBeenCalledWith(
        expect.objectContaining({ sessionId: "s-x" }),
      );
    });
  });

  // ── log_action ────────────────────────────────────────────────────────────

  describe("log_action", () => {
    it("calls client.actions.log with agentId and toolName", async () => {
      const tools = crewLayerTools({ client, agentId: "ag-1" });
      await tools.log_action.execute({ toolName: "my.tool" });
      expect(client.actions.log).toHaveBeenCalledWith(
        expect.objectContaining({ agentId: "ag-1", toolName: "my.tool" }),
      );
    });

    it("defaults status to 'success'", async () => {
      const tools = crewLayerTools({ client, agentId: "ag-1" });
      await tools.log_action.execute({ toolName: "t" });
      expect(client.actions.log).toHaveBeenCalledWith(
        expect.objectContaining({ status: "success" }),
      );
    });

    it("forwards 'error' status", async () => {
      const tools = crewLayerTools({ client, agentId: "ag-1" });
      await tools.log_action.execute({ toolName: "t", status: "error" });
      expect(client.actions.log).toHaveBeenCalledWith(
        expect.objectContaining({ status: "error" }),
      );
    });

    it("returns { id, logged: true }", async () => {
      const tools = crewLayerTools({ client, agentId: "ag-1" });
      const result = await tools.log_action.execute({ toolName: "t" });
      expect(result.logged).toBe(true);
      expect(typeof result.id).toBe("string");
    });

    it("includes inputSummary in inputParams", async () => {
      const tools = crewLayerTools({ client, agentId: "ag-1" });
      await tools.log_action.execute({ toolName: "t", inputSummary: "did something" });
      expect(client.actions.log).toHaveBeenCalledWith(
        expect.objectContaining({ inputParams: { summary: "did something" } }),
      );
    });
  });

  // ── read_context ──────────────────────────────────────────────────────────

  describe("read_context", () => {
    it("calls client.context.read with namespace and key", async () => {
      const tools = crewLayerTools({ client, agentId: "ag-1" });
      await tools.read_context.execute({ namespace: "proj:x", key: "status" });
      expect(client.context.read).toHaveBeenCalledWith({ namespace: "proj:x", key: "status" });
    });

    it("returns the value and version from the context entry", async () => {
      (client.context.read as ReturnType<typeof vi.fn>).mockResolvedValue({
        id: "c1",
        tenantId: "t1",
        namespace: "ns",
        key: "k",
        value: { state: "active" },
        version: 7,
        createdAt: "",
        updatedAt: "",
      });
      const tools = crewLayerTools({ client, agentId: "ag-1" });
      const result = await tools.read_context.execute({ namespace: "ns", key: "k" });
      expect(result.value).toEqual({ state: "active" });
      expect(result.version).toBe(7);
    });
  });

  // ── write_context ─────────────────────────────────────────────────────────

  describe("write_context", () => {
    it("calls client.context.write with the parsed JSON value", async () => {
      const tools = crewLayerTools({ client, agentId: "ag-1" });
      await tools.write_context.execute({
        namespace: "ns",
        key: "k",
        value: JSON.stringify({ done: true }),
      });
      expect(client.context.write).toHaveBeenCalledWith(
        expect.objectContaining({ namespace: "ns", key: "k", value: { done: true } }),
      );
    });

    it("wraps non-JSON string in { text }", async () => {
      const tools = crewLayerTools({ client, agentId: "ag-1" });
      await tools.write_context.execute({ namespace: "ns", key: "k", value: "plain text" });
      expect(client.context.write).toHaveBeenCalledWith(
        expect.objectContaining({ value: { text: "plain text" } }),
      );
    });

    it("wraps a JSON primitive in { text }", async () => {
      const tools = crewLayerTools({ client, agentId: "ag-1" });
      await tools.write_context.execute({ namespace: "ns", key: "k", value: '"just a string"' });
      expect(client.context.write).toHaveBeenCalledWith(
        expect.objectContaining({ value: { text: '"just a string"' } }),
      );
    });

    it("wraps a JSON array in { text }", async () => {
      const tools = crewLayerTools({ client, agentId: "ag-1" });
      await tools.write_context.execute({ namespace: "ns", key: "k", value: "[1,2,3]" });
      expect(client.context.write).toHaveBeenCalledWith(
        expect.objectContaining({ value: { text: "[1,2,3]" } }),
      );
    });

    it("returns { version, written: true }", async () => {
      const tools = crewLayerTools({ client, agentId: "ag-1" });
      const result = await tools.write_context.execute({ namespace: "ns", key: "k", value: "{}" });
      expect(result.written).toBe(true);
      expect(typeof result.version).toBe("number");
    });
  });
});

// ---------------------------------------------------------------------------
// CrewLayerDataStream
// ---------------------------------------------------------------------------

describe("CrewLayerDataStream", () => {
  let client: CrewLayerClient;

  beforeEach(() => {
    client = makeMockClient();
  });

  it("yields all chunks from the source in order", async () => {
    const stream = new CrewLayerDataStream(textSource(["Hello", " ", "world"]), {
      client,
      agentId: "ag-1",
    });
    const chunks: string[] = [];
    for await (const chunk of stream) {
      chunks.push(chunk);
    }
    expect(chunks).toEqual(["Hello", " ", "world"]);
  });

  it("logs a success action with accumulated text on normal completion", async () => {
    const stream = new CrewLayerDataStream(textSource(["foo", "bar"]), {
      client,
      agentId: "ag-1",
    });
    for await (const _ of stream) { /* consume */ }
    expect(client.actions.log).toHaveBeenCalledWith(
      expect.objectContaining({
        agentId: "ag-1",
        status: "success",
        outputResult: expect.objectContaining({ text: "foobar" }),
      }),
    );
  });

  it("logs an error action with errorMsg when the source throws", async () => {
    const stream = new CrewLayerDataStream(failingSource(["a", "b"], 1), {
      client,
      agentId: "ag-1",
    });
    let thrown = false;
    try {
      for await (const _ of stream) { /* consume */ }
    } catch {
      thrown = true;
    }
    expect(thrown).toBe(true);
    expect(client.actions.log).toHaveBeenCalledWith(
      expect.objectContaining({ status: "error", errorMsg: "stream failure" }),
    );
  });

  it("uses the configured toolName", async () => {
    const stream = new CrewLayerDataStream(textSource(["x"]), {
      client,
      agentId: "ag-1",
      toolName: "my.stream",
    });
    for await (const _ of stream) { /* consume */ }
    expect(client.actions.log).toHaveBeenCalledWith(
      expect.objectContaining({ toolName: "my.stream" }),
    );
  });

  it("defaults toolName to 'vercel.stream'", async () => {
    const stream = new CrewLayerDataStream(textSource(["x"]), { client, agentId: "ag-1" });
    for await (const _ of stream) { /* consume */ }
    expect(client.actions.log).toHaveBeenCalledWith(
      expect.objectContaining({ toolName: "vercel.stream" }),
    );
  });

  it("includes a numeric durationMs in the logged action", async () => {
    const stream = new CrewLayerDataStream(textSource(["x"]), { client, agentId: "ag-1" });
    for await (const _ of stream) { /* consume */ }
    const call = (client.actions.log as ReturnType<typeof vi.fn>).mock.calls[0][0] as {
      durationMs: unknown;
    };
    expect(typeof call.durationMs).toBe("number");
    expect(call.durationMs as number).toBeGreaterThanOrEqual(0);
  });

  it("does not throw if the action log call fails", async () => {
    (client.actions.log as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("log fail"));
    const stream = new CrewLayerDataStream(textSource(["a"]), { client, agentId: "ag-1" });
    const chunks: string[] = [];
    for await (const chunk of stream) {
      chunks.push(chunk);
    }
    expect(chunks).toEqual(["a"]);
  });

  it("truncates the accumulated text to 2000 chars in the log output", async () => {
    const big = "x".repeat(3000);
    const stream = new CrewLayerDataStream(textSource([big]), { client, agentId: "ag-1" });
    for await (const _ of stream) { /* consume */ }
    const call = (client.actions.log as ReturnType<typeof vi.fn>).mock.calls[0][0] as {
      outputResult: Record<string, string>;
    };
    expect(call.outputResult.text.length).toBeLessThanOrEqual(2000);
  });

  it("forwards sessionId to the logged action", async () => {
    const stream = new CrewLayerDataStream(textSource(["a"]), {
      client,
      agentId: "ag-1",
      sessionId: "s-42",
    });
    for await (const _ of stream) { /* consume */ }
    expect(client.actions.log).toHaveBeenCalledWith(
      expect.objectContaining({ sessionId: "s-42" }),
    );
  });

  // ── toResponse() ──────────────────────────────────────────────────────────

  describe("toResponse()", () => {
    it("returns a Response instance", () => {
      const stream = new CrewLayerDataStream(textSource(["a"]), { client, agentId: "ag-1" });
      expect(stream.toResponse()).toBeInstanceOf(Response);
    });

    it("defaults to HTTP 200", () => {
      const stream = new CrewLayerDataStream(textSource([]), { client, agentId: "ag-1" });
      expect(stream.toResponse().status).toBe(200);
    });

    it("respects a custom status code", () => {
      const stream = new CrewLayerDataStream(textSource([]), { client, agentId: "ag-1" });
      expect(stream.toResponse({ status: 201 }).status).toBe(201);
    });

    it("sets Content-Type to text/plain", () => {
      const stream = new CrewLayerDataStream(textSource([]), { client, agentId: "ag-1" });
      expect(stream.toResponse().headers.get("content-type")).toContain("text/plain");
    });

    it("streams all chunks through the response body", async () => {
      const stream = new CrewLayerDataStream(textSource(["Hello", " world"]), {
        client,
        agentId: "ag-1",
      });
      const response = stream.toResponse();
      expect(response.body).not.toBeNull();
      const text = await response.text();
      expect(text).toBe("Hello world");
    });

    it("accepts custom headers via ResponseInit", () => {
      const stream = new CrewLayerDataStream(textSource([]), { client, agentId: "ag-1" });
      const response = stream.toResponse({
        headers: { "X-Custom": "yes" },
      });
      expect(response.headers.get("x-custom")).toBe("yes");
    });
  });
});
