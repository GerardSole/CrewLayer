import { describe, it, expect, vi, afterEach } from "vitest";
import { createClient, mockFetch, lastFetchCall } from "./helpers.js";

afterEach(() => vi.unstubAllGlobals());

const AGENT = {
  id: "agent-001",
  tenantId: "tenant-001",
  name: "Test Agent",
  description: "A test agent",
  config: {},
  status: "idle",
  tags: ["test"],
  statusUpdatedAt: "2026-01-01T00:00:00Z",
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

describe("agents.create", () => {
  it("calls POST /v1/agents", async () => {
    mockFetch(AGENT);
    const client = createClient();
    const result = await client.agents.create({ name: "Test Agent", tags: ["test"] });

    const { url, init } = lastFetchCall();
    expect(url).toBe("http://test.local/v1/agents");
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body as string);
    expect(body.name).toBe("Test Agent");
    expect(body.tags).toEqual(["test"]);
    expect(result.id).toBe("agent-001");
  });
});

describe("agents.list", () => {
  it("calls GET /v1/agents", async () => {
    mockFetch({ items: [AGENT], total: 1, page: 1, pageSize: 20 });
    const client = createClient();
    const result = await client.agents.list({ status: "idle", tags: ["test"] });

    const { url } = lastFetchCall();
    expect(url).toContain("/v1/agents");
    expect(url).toContain("status=idle");
    expect(url).toContain("tags=test");
    expect(result.items).toHaveLength(1);
  });
});

describe("agents.get", () => {
  it("calls GET /v1/agents/{id}", async () => {
    mockFetch(AGENT);
    const client = createClient();
    const result = await client.agents.get("agent-001");

    const { url } = lastFetchCall();
    expect(url).toBe("http://test.local/v1/agents/agent-001");
    expect(result.name).toBe("Test Agent");
  });
});

describe("agents.update", () => {
  it("calls PATCH /v1/agents/{id}", async () => {
    mockFetch({ ...AGENT, name: "Updated" });
    const client = createClient();
    const result = await client.agents.update("agent-001", { name: "Updated" });

    const { url, init } = lastFetchCall();
    expect(url).toBe("http://test.local/v1/agents/agent-001");
    expect(init.method).toBe("PATCH");
    const body = JSON.parse(init.body as string);
    expect(body.name).toBe("Updated");
    expect(result.name).toBe("Updated");
  });
});

describe("agents.delete", () => {
  it("calls DELETE /v1/agents/{id}", async () => {
    mockFetch(null, 204);
    const client = createClient();
    await client.agents.delete("agent-001");

    const { url, init } = lastFetchCall();
    expect(url).toBe("http://test.local/v1/agents/agent-001");
    expect(init.method).toBe("DELETE");
  });
});

describe("agents.getStatus", () => {
  it("calls GET /v1/agents/{id}/status", async () => {
    const status = { agentId: "agent-001", status: "idle", statusUpdatedAt: "2026-01-01T00:00:00Z" };
    mockFetch(status);
    const client = createClient();
    const result = await client.agents.getStatus("agent-001");

    const { url } = lastFetchCall();
    expect(url).toBe("http://test.local/v1/agents/agent-001/status");
    expect(result.status).toBe("idle");
  });
});

describe("agents.setStatus", () => {
  it("calls PATCH /v1/agents/{id}/status", async () => {
    mockFetch({ ...AGENT, status: "working" });
    const client = createClient();
    await client.agents.setStatus({ agentId: "agent-001", status: "working", sessionId: "sess-001" });

    const { url, init } = lastFetchCall();
    expect(url).toBe("http://test.local/v1/agents/agent-001/status");
    expect(init.method).toBe("PATCH");
    const body = JSON.parse(init.body as string);
    expect(body.status).toBe("working");
    expect(body.session_id).toBe("sess-001");
  });
});

describe("agents.setRelation", () => {
  it("calls POST /v1/agents/{id}/relations", async () => {
    const rel = { supervisorId: "agent-001", subordinateId: "agent-002", relationType: "supervisor", createdAt: "2026-01-01T00:00:00Z" };
    mockFetch(rel);
    const client = createClient();
    await client.agents.setRelation({ agentId: "agent-001", targetId: "agent-002", relationType: "supervisor" });

    const { url, init } = lastFetchCall();
    expect(url).toBe("http://test.local/v1/agents/agent-001/relations");
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body as string);
    expect(body.target_id).toBe("agent-002");
    expect(body.relation_type).toBe("supervisor");
  });
});

describe("agents.export / agents.import", () => {
  it("export calls GET /v1/agents/{id}/export", async () => {
    const exportData = { exportVersion: "1.0", agent: AGENT, memories: [], actions: [], episodes: [], sessions: [], episodeMemories: [], relations: [], exportedAt: "2026-01-01T00:00:00Z" };
    mockFetch(exportData);
    const client = createClient();
    const result = await client.agents.export("agent-001");

    const { url, init } = lastFetchCall();
    expect(url).toBe("http://test.local/v1/agents/agent-001/export");
    expect(init.method).toBe("GET");
    expect(result.exportVersion).toBe("1.0");
  });

  it("import calls POST /v1/agents/import", async () => {
    const importResp = { agent: AGENT, idMap: { "old-mem-id": "new-mem-id" }, warnings: [] };
    mockFetch(importResp);
    const client = createClient();
    const data = { exportVersion: "1.0", agent: AGENT, memories: [], actions: [], episodes: [], sessions: [], episodeMemories: [], relations: [], exportedAt: "2026-01-01T00:00:00Z" };
    const result = await client.agents.import(data);

    const { url, init } = lastFetchCall();
    expect(url).toBe("http://test.local/v1/agents/import");
    expect(init.method).toBe("POST");
    expect(result.agent.id).toBe("agent-001");
  });
});
