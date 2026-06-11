import { describe, it, expect, vi, afterEach } from "vitest";
import { createClient, mockFetch, lastFetchCall } from "./helpers.js";

afterEach(() => vi.unstubAllGlobals());

const AGENT_ID = "agent-001";

const EPISODE = {
  id: "ep-001",
  tenantId: "tenant-001",
  agentId: AGENT_ID,
  title: "Bug investigation",
  status: "active",
  startedAt: "2026-01-01T00:00:00Z",
  metadata: {},
};

describe("episodes.create", () => {
  it("calls POST /v1/agents/{id}/episodes", async () => {
    mockFetch(EPISODE);
    const client = createClient();
    const result = await client.episodes.create({ agentId: AGENT_ID, title: "Bug investigation" });

    const { url, init } = lastFetchCall();
    expect(url).toBe(`http://test.local/v1/agents/${AGENT_ID}/episodes`);
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body as string);
    expect(body.title).toBe("Bug investigation");
    expect(result.id).toBe("ep-001");
  });
});

describe("episodes.list", () => {
  it("calls GET /v1/agents/{id}/episodes with status filter", async () => {
    mockFetch({ items: [EPISODE], total: 1 });
    const client = createClient();
    await client.episodes.list({ agentId: AGENT_ID, status: "active" });

    const { url } = lastFetchCall();
    expect(url).toContain(`/v1/agents/${AGENT_ID}/episodes`);
    expect(url).toContain("status=active");
  });
});

describe("episodes.get", () => {
  it("calls GET /v1/agents/{id}/episodes/{epId}", async () => {
    mockFetch({ ...EPISODE, sessions: [], memories: [] });
    const client = createClient();
    const result = await client.episodes.get(AGENT_ID, "ep-001");

    const { url } = lastFetchCall();
    expect(url).toBe(`http://test.local/v1/agents/${AGENT_ID}/episodes/ep-001`);
    expect(result.id).toBe("ep-001");
  });
});

describe("episodes.complete", () => {
  it("calls POST /v1/agents/{id}/episodes/{epId}/complete", async () => {
    mockFetch({ ...EPISODE, status: "completed", completedAt: "2026-01-01T02:00:00Z" });
    const client = createClient();
    const result = await client.episodes.complete(AGENT_ID, "ep-001");

    const { url, init } = lastFetchCall();
    expect(url).toBe(`http://test.local/v1/agents/${AGENT_ID}/episodes/ep-001/complete`);
    expect(init.method).toBe("POST");
    expect(result.status).toBe("completed");
  });
});

describe("episodes.recall", () => {
  it("calls POST /v1/agents/{id}/episodes/{epId}/recall", async () => {
    mockFetch([]);
    const client = createClient();
    await client.episodes.recall({ agentId: AGENT_ID, episodeId: "ep-001", query: "bug fix", limit: 5 });

    const { url, init } = lastFetchCall();
    expect(url).toBe(`http://test.local/v1/agents/${AGENT_ID}/episodes/ep-001/recall`);
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body as string);
    expect(body.query).toBe("bug fix");
    expect(body.limit).toBe(5);
  });
});
