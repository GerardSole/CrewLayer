import { describe, it, expect, vi, afterEach } from "vitest";
import { createClient, mockFetch, lastFetchCall } from "./helpers.js";

afterEach(() => vi.unstubAllGlobals());

const AGENT_ID = "agent-001";

const SHORT_MEMORY = {
  sessionId: "sess-001",
  messages: [{ role: "user", content: "hello", metadata: {} }],
  count: 1,
};

const MEMORY_ITEM = {
  id: "mem-001",
  agentId: AGENT_ID,
  content: "user prefers dark mode",
  importance: 0.8,
  tags: ["preference"],
  status: "active",
  accessCount: 2,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

describe("memory.append", () => {
  it("calls POST /v1/agents/{id}/memory/messages", async () => {
    mockFetch(SHORT_MEMORY);
    const client = createClient();
    const result = await client.memory.append({
      agentId: AGENT_ID,
      role: "user",
      content: "hello",
      sessionId: "sess-001",
    });

    const { url, init } = lastFetchCall();
    expect(url).toBe(`http://test.local/v1/agents/${AGENT_ID}/memory/messages`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toMatchObject({ role: "user", content: "hello", session_id: "sess-001" });
    expect(result).toEqual(SHORT_MEMORY);
  });
});

describe("memory.messages", () => {
  it("calls GET /v1/agents/{id}/memory/messages with session_id param", async () => {
    mockFetch(SHORT_MEMORY);
    const client = createClient();
    await client.memory.messages({ agentId: AGENT_ID, sessionId: "sess-001" });

    const { url, init } = lastFetchCall();
    expect(url).toContain(`/v1/agents/${AGENT_ID}/memory/messages`);
    expect(url).toContain("session_id=sess-001");
    expect(init.method).toBe("GET");
  });
});

describe("memory.recall", () => {
  it("calls POST /v1/agents/{id}/memory/recall", async () => {
    const recall = { query: "preferencias", results: [MEMORY_ITEM] };
    mockFetch(recall);
    const client = createClient();
    const result = await client.memory.recall({ agentId: AGENT_ID, query: "preferencias", limit: 5 });

    const { url, init } = lastFetchCall();
    expect(url).toBe(`http://test.local/v1/agents/${AGENT_ID}/memory/recall`);
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body as string);
    expect(body.query).toBe("preferencias");
    expect(body.limit).toBe(5);
    expect(result.results).toHaveLength(1);
  });

  it("passes minSimilarity as min_similarity", async () => {
    mockFetch({ query: "x", results: [] });
    const client = createClient();
    await client.memory.recall({ agentId: AGENT_ID, query: "x", minSimilarity: 0.7 });

    const body = JSON.parse(lastFetchCall().init.body as string);
    expect(body.min_similarity).toBe(0.7);
  });
});

describe("memory.extract", () => {
  it("calls POST /v1/agents/{id}/memory/extract", async () => {
    const result = { extractedCount: 3, memoryIds: ["m1", "m2", "m3"] };
    mockFetch(result);
    const client = createClient();
    const res = await client.memory.extract({ agentId: AGENT_ID, sessionId: "sess-001" });

    const { url, init } = lastFetchCall();
    expect(url).toBe(`http://test.local/v1/agents/${AGENT_ID}/memory/extract`);
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body as string);
    expect(body.session_id).toBe("sess-001");
    expect(res.extractedCount).toBe(3);
  });
});

describe("memory.list", () => {
  it("calls GET /v1/agents/{id}/memory", async () => {
    const page = { items: [MEMORY_ITEM], total: 1, page: 1, pageSize: 20 };
    mockFetch(page);
    const client = createClient();
    const result = await client.memory.list({ agentId: AGENT_ID, includeArchived: true });

    const { url } = lastFetchCall();
    expect(url).toContain(`/v1/agents/${AGENT_ID}/memory`);
    expect(url).toContain("include_archived=true");
    expect(result.items).toHaveLength(1);
  });
});

describe("memory.delete", () => {
  it("calls DELETE /v1/agents/{id}/memory/{memId}", async () => {
    mockFetch(null, 204);
    const client = createClient();
    await client.memory.delete({ agentId: AGENT_ID, memoryId: "mem-001" });

    const { url, init } = lastFetchCall();
    expect(url).toBe(`http://test.local/v1/agents/${AGENT_ID}/memory/mem-001`);
    expect(init.method).toBe("DELETE");
  });
});

describe("memory.stats", () => {
  it("calls GET /v1/agents/{id}/memory/stats", async () => {
    const stats = { agentId: AGENT_ID, totalMemories: 10, activeMemories: 8, archivedMemories: 2, avgImportance: 0.6 };
    mockFetch(stats);
    const client = createClient();
    const result = await client.memory.stats(AGENT_ID);

    const { url } = lastFetchCall();
    expect(url).toBe(`http://test.local/v1/agents/${AGENT_ID}/memory/stats`);
    expect(result.totalMemories).toBe(10);
  });
});
