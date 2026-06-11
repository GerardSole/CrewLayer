import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { createClient, mockFetchSeq } from "./helpers.js";
import { ServerError, AuthError } from "../src/errors.js";

afterEach(() => vi.unstubAllGlobals());

// Speed up retry tests by mocking timers
beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

function makeResponse(status: number, body: unknown = {}): Response {
  return {
    ok: status < 400,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
    body: null,
    headers: new Headers(),
  } as unknown as Response;
}

describe("retry behavior", () => {
  it("retries on 503 and succeeds on second attempt", async () => {
    const agent = { id: "a", name: "x", status: "idle", tenantId: "t", config: {}, tags: [], statusUpdatedAt: "", createdAt: "", updatedAt: "" };
    mockFetchSeq([{}, 503], [agent, 200]);
    const client = createClient();

    const promise = client.agents.get("a");
    // advance timer to trigger retry (2^0 = 1s)
    await vi.runAllTimersAsync();
    const result = await promise;
    expect(result.id).toBe("a");
    expect(vi.mocked(fetch).mock.calls).toHaveLength(2);
  });

  it("throws ServerError after max retries (3 retries = 4 total calls)", async () => {
    mockFetchSeq(
      [{}, 503],
      [{}, 503],
      [{}, 503],
      [{}, 503],
    );
    const client = createClient();

    const promise = client.agents.get("a");
    // Register rejection handler BEFORE advancing timers to avoid unhandled rejection warning
    const expectation = expect(promise).rejects.toBeInstanceOf(ServerError);
    await vi.runAllTimersAsync();
    await expectation;
    expect(vi.mocked(fetch).mock.calls).toHaveLength(4);
  });

  it("does NOT retry on 401", async () => {
    mockFetchSeq([{ detail: "bad key" }, 401]);
    const client = createClient();

    await expect(client.agents.get("a")).rejects.toBeInstanceOf(AuthError);
    expect(vi.mocked(fetch).mock.calls).toHaveLength(1);
  });

  it("does NOT retry on 404", async () => {
    mockFetchSeq([{ detail: "not found" }, 404]);
    const client = createClient();

    const { NotFoundError } = await import("../src/errors.js");
    await expect(client.agents.get("missing")).rejects.toBeInstanceOf(NotFoundError);
    expect(vi.mocked(fetch).mock.calls).toHaveLength(1);
  });

  it("retries on 500, 502, 503, 504 but not on 400, 422, 429", async () => {
    for (const status of [500, 502, 503, 504]) {
      vi.unstubAllGlobals();
      mockFetchSeq([{}, status], [{ id: "a", name: "x", status: "idle", tenantId: "t", config: {}, tags: [], statusUpdatedAt: "", createdAt: "", updatedAt: "" }, 200]);
      const client = createClient();
      const promise = client.agents.get("a");
      await vi.runAllTimersAsync();
      await promise;
      expect(vi.mocked(fetch).mock.calls).toHaveLength(2);
    }
  });
});
