import { describe, it, expect, vi, afterEach } from "vitest";
import { createClient, mockFetch, lastFetchCall } from "./helpers.js";

afterEach(() => vi.unstubAllGlobals());

const AGENT_ID = "agent-001";

const ACTION = {
  id: "act-001",
  tenantId: "tenant-001",
  agentId: AGENT_ID,
  toolName: "web_search",
  inputParams: { query: "hello" },
  outputResult: { results: [] },
  status: "success",
  timestamp: "2026-01-01T00:00:00Z",
  metadata: {},
};

describe("actions.log", () => {
  it("calls POST /v1/agents/{id}/actions", async () => {
    mockFetch(ACTION);
    const client = createClient();
    const result = await client.actions.log({
      agentId: AGENT_ID,
      toolName: "web_search",
      inputParams: { query: "hello" },
      outputResult: { results: [] },
      status: "success",
      durationMs: 120,
    });

    const { url, init } = lastFetchCall();
    expect(url).toBe(`http://test.local/v1/agents/${AGENT_ID}/actions`);
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body as string);
    expect(body.tool_name).toBe("web_search");
    expect(body.duration_ms).toBe(120);
    expect(result.id).toBe("act-001");
  });

  it("defaults status to success", async () => {
    mockFetch(ACTION);
    const client = createClient();
    await client.actions.log({ agentId: AGENT_ID, toolName: "tool" });

    const body = JSON.parse(lastFetchCall().init.body as string);
    expect(body.status).toBe("success");
  });
});

describe("actions.get", () => {
  it("calls GET /v1/agents/{id}/actions/{actionId}", async () => {
    mockFetch(ACTION);
    const client = createClient();
    const result = await client.actions.get(AGENT_ID, "act-001");

    const { url, init } = lastFetchCall();
    expect(url).toBe(`http://test.local/v1/agents/${AGENT_ID}/actions/act-001`);
    expect(init.method).toBe("GET");
    expect(result.id).toBe("act-001");
  });
});

describe("actions.list", () => {
  it("calls GET /v1/agents/{id}/actions with filters", async () => {
    const page = { items: [ACTION], count: 1 };
    mockFetch(page);
    const client = createClient();
    await client.actions.list({ agentId: AGENT_ID, status: "success", toolName: "web_search", limit: 10 });

    const { url } = lastFetchCall();
    expect(url).toContain(`/v1/agents/${AGENT_ID}/actions`);
    expect(url).toContain("status=success");
    expect(url).toContain("tool_name=web_search");
    expect(url).toContain("limit=10");
  });
});

describe("actions.stats", () => {
  it("calls GET /v1/agents/{id}/actions/stats", async () => {
    const stats = {
      agentId: AGENT_ID,
      totalActions: 50,
      errorRate: 0.02,
      byTool: [{ toolName: "web_search", count: 50, errorRate: 0.02 }],
    };
    mockFetch(stats);
    const client = createClient();
    const result = await client.actions.stats(AGENT_ID);

    const { url } = lastFetchCall();
    expect(url).toBe(`http://test.local/v1/agents/${AGENT_ID}/actions/stats`);
    expect(result.totalActions).toBe(50);
  });
});
