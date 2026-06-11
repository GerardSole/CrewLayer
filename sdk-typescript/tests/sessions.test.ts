import { describe, it, expect, vi, afterEach } from "vitest";
import { createClient, mockFetch, lastFetchCall } from "./helpers.js";

afterEach(() => vi.unstubAllGlobals());

const SESSION = {
  id: "sess-001",
  tenantId: "tenant-001",
  agentId: "agent-001",
  status: "active",
  messageCount: 0,
  startedAt: "2026-01-01T00:00:00Z",
  metadata: {},
};

describe("sessions.create", () => {
  it("calls POST /v1/sessions with agent_id", async () => {
    mockFetch(SESSION);
    const client = createClient();
    const result = await client.sessions.create({ agentId: "agent-001" });

    const { url, init } = lastFetchCall();
    expect(url).toBe("http://test.local/v1/sessions");
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body as string);
    expect(body.agent_id).toBe("agent-001");
    expect(result.id).toBe("sess-001");
  });

  it("passes episode_id when provided", async () => {
    mockFetch(SESSION);
    const client = createClient();
    await client.sessions.create({ agentId: "agent-001", episodeId: "ep-001" });

    const body = JSON.parse(lastFetchCall().init.body as string);
    expect(body.episode_id).toBe("ep-001");
  });
});

describe("sessions.get", () => {
  it("calls GET /v1/sessions/{id}", async () => {
    mockFetch(SESSION);
    const client = createClient();
    const result = await client.sessions.get("sess-001");

    const { url } = lastFetchCall();
    expect(url).toBe("http://test.local/v1/sessions/sess-001");
    expect(result.agentId).toBe("agent-001");
  });
});

describe("sessions.close", () => {
  it("calls POST /v1/sessions/{id}/close", async () => {
    mockFetch({ ...SESSION, status: "closed", closedAt: "2026-01-01T01:00:00Z" });
    const client = createClient();
    const result = await client.sessions.close("sess-001");

    const { url, init } = lastFetchCall();
    expect(url).toBe("http://test.local/v1/sessions/sess-001/close");
    expect(init.method).toBe("POST");
    expect(result.status).toBe("closed");
  });
});

describe("sessions.update", () => {
  it("calls PATCH /v1/sessions/{id}", async () => {
    mockFetch({ ...SESSION, episodeId: "ep-001" });
    const client = createClient();
    await client.sessions.update({ sessionId: "sess-001", episodeId: "ep-001" });

    const { url, init } = lastFetchCall();
    expect(url).toBe("http://test.local/v1/sessions/sess-001");
    expect(init.method).toBe("PATCH");
    const body = JSON.parse(init.body as string);
    expect(body.episode_id).toBe("ep-001");
  });
});

describe("sessions.list", () => {
  it("calls GET /v1/sessions with filters", async () => {
    mockFetch({ items: [SESSION], total: 1 });
    const client = createClient();
    await client.sessions.list({ agentId: "agent-001", status: "active" });

    const { url } = lastFetchCall();
    expect(url).toContain("/v1/sessions");
    expect(url).toContain("agent_id=agent-001");
    expect(url).toContain("status=active");
  });
});
