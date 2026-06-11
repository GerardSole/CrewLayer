import { vi } from "vitest";
import { CrewLayerClient } from "../src/client.js";

export function createClient(): CrewLayerClient {
  return new CrewLayerClient({ apiKey: "crwl_test", baseUrl: "http://test.local" });
}

export function mockFetch(data: unknown, status = 200): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: status < 400,
      status,
      json: () => Promise.resolve(data),
      text: () => Promise.resolve(JSON.stringify(data)),
      body: null,
      headers: new Headers({ "content-type": "application/json" }),
    } satisfies Partial<Response> as unknown as Response)
  );
}

export function mockFetchSeq(...responses: Array<[unknown, number?]>): void {
  const mock = vi.fn();
  for (const [data, status = 200] of responses) {
    mock.mockResolvedValueOnce({
      ok: status < 400,
      status,
      json: () => Promise.resolve(data),
      text: () => Promise.resolve(JSON.stringify(data)),
      body: null,
      headers: new Headers({ "content-type": "application/json" }),
    } satisfies Partial<Response> as unknown as Response);
  }
  vi.stubGlobal("fetch", mock);
}

/** Returns the last URL+init that fetch was called with. */
export function lastFetchCall(): { url: string; init: RequestInit } {
  const mock = vi.mocked(globalThis.fetch);
  const call = mock.mock.calls[mock.mock.calls.length - 1];
  if (!call) throw new Error("fetch was not called");
  return { url: call[0] as string, init: (call[1] ?? {}) as RequestInit };
}
