import { describe, it, expect, vi, afterEach } from "vitest";
import { createClient, mockFetch, lastFetchCall } from "./helpers.js";

afterEach(() => vi.unstubAllGlobals());

const ENTRY = {
  id: "ctx-001",
  tenantId: "tenant-001",
  namespace: "proj:abc",
  key: "status",
  value: { phase: "init" },
  version: 1,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
};

describe("context.write", () => {
  it("calls PUT /v1/context/{ns}/{key}", async () => {
    mockFetch(ENTRY);
    const client = createClient();
    const result = await client.context.write({
      namespace: "proj:abc",
      key: "status",
      value: { phase: "init" },
    });

    const { url, init } = lastFetchCall();
    expect(url).toBe("http://test.local/v1/context/proj:abc/status");
    expect(init.method).toBe("PUT");
    const body = JSON.parse(init.body as string);
    expect(body.value).toEqual({ phase: "init" });
    expect(result.version).toBe(1);
  });

  it("sends expected_version for optimistic locking", async () => {
    mockFetch(ENTRY);
    const client = createClient();
    await client.context.write({
      namespace: "proj:abc",
      key: "status",
      value: { phase: "running" },
      expectedVersion: 1,
    });

    const body = JSON.parse(lastFetchCall().init.body as string);
    expect(body.expected_version).toBe(1);
  });
});

describe("context.read", () => {
  it("calls GET /v1/context/{ns}/{key}", async () => {
    mockFetch(ENTRY);
    const client = createClient();
    const result = await client.context.read({ namespace: "proj:abc", key: "status" });

    const { url, init } = lastFetchCall();
    expect(url).toBe("http://test.local/v1/context/proj:abc/status");
    expect(init.method).toBe("GET");
    expect(result.key).toBe("status");
  });
});

describe("context.delete", () => {
  it("calls DELETE /v1/context/{ns}/{key}", async () => {
    mockFetch(null, 204);
    const client = createClient();
    await client.context.delete({ namespace: "proj:abc", key: "status" });

    const { url, init } = lastFetchCall();
    expect(url).toBe("http://test.local/v1/context/proj:abc/status");
    expect(init.method).toBe("DELETE");
  });
});

describe("context.listNamespace", () => {
  it("calls GET /v1/context/{ns}", async () => {
    const ns = { namespace: "proj:abc", entries: [ENTRY], count: 1 };
    mockFetch(ns);
    const client = createClient();
    const result = await client.context.listNamespace({ namespace: "proj:abc" });

    const { url } = lastFetchCall();
    expect(url).toBe("http://test.local/v1/context/proj:abc");
    expect(result.count).toBe(1);
  });
});

describe("context.history", () => {
  it("calls GET /v1/context/{ns}/{key}/history", async () => {
    mockFetch([]);
    const client = createClient();
    await client.context.history({ namespace: "proj:abc", key: "status", limit: 20 });

    const { url } = lastFetchCall();
    expect(url).toContain("/v1/context/proj:abc/status/history");
    expect(url).toContain("limit=20");
  });
});

describe("context.rollback", () => {
  it("calls POST /v1/context/{ns}/{key}/rollback", async () => {
    mockFetch(ENTRY);
    const client = createClient();
    await client.context.rollback({ namespace: "proj:abc", key: "status", version: 1 });

    const { url, init } = lastFetchCall();
    expect(url).toBe("http://test.local/v1/context/proj:abc/status/rollback");
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body as string);
    expect(body.version).toBe(1);
  });
});

describe("context.subscribe", () => {
  it("returns an SSEStream with on/off/close methods", () => {
    const client = createClient();
    // Don't actually open the connection in tests — just check the interface
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => undefined)));

    const stream = client.context.subscribe({ namespace: "proj:abc", key: "status" });
    expect(typeof stream.on).toBe("function");
    expect(typeof stream.off).toBe("function");
    expect(typeof stream.close).toBe("function");
    stream.close();
  });
});
