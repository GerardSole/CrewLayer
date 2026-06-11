import { describe, it, expect, vi, afterEach } from "vitest";
import { SSEStream, openContextStream } from "../src/streaming.js";
import type { ContextStreamEvents } from "../src/streaming.js";

afterEach(() => vi.unstubAllGlobals());

// Helper to create a mock ReadableStream that emits SSE lines
function sseStream(events: Array<{ event: string; data: string }>): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let idx = 0;
  return new ReadableStream({
    pull(controller) {
      if (idx >= events.length) {
        controller.close();
        return;
      }
      const { event, data } = events[idx++]!;
      const chunk = `event: ${event}\ndata: ${data}\n\n`;
      controller.enqueue(encoder.encode(chunk));
    },
  });
}

describe("SSEStream", () => {
  it("on/off/close methods exist", () => {
    const stream = new SSEStream<ContextStreamEvents>();
    expect(typeof stream.on).toBe("function");
    expect(typeof stream.off).toBe("function");
    expect(typeof stream.close).toBe("function");
  });

  it("on registers a listener and _emit calls it", () => {
    const stream = new SSEStream<ContextStreamEvents>();
    const entry = { id: "1", tenantId: "t", namespace: "ns", key: "k", value: {}, version: 1, createdAt: "", updatedAt: "" };
    const handler = vi.fn();
    stream.on("updated", handler);
    stream._emit("updated", entry);
    expect(handler).toHaveBeenCalledWith(entry);
  });

  it("off removes a listener", () => {
    const stream = new SSEStream<ContextStreamEvents>();
    const handler = vi.fn();
    stream.on("updated", handler);
    stream.off("updated", handler);
    stream._emit("updated", { id: "1", tenantId: "t", namespace: "ns", key: "k", value: {}, version: 1, createdAt: "", updatedAt: "" });
    expect(handler).not.toHaveBeenCalled();
  });

  it("close aborts the signal", () => {
    const stream = new SSEStream<ContextStreamEvents>();
    expect(stream.signal.aborted).toBe(false);
    stream.close();
    expect(stream.signal.aborted).toBe(true);
  });

  it("supports method chaining with on", () => {
    const stream = new SSEStream<ContextStreamEvents>();
    const result = stream.on("updated", () => undefined);
    expect(result).toBe(stream);
  });
});

describe("openContextStream", () => {
  it("emits 'updated' events from SSE stream", async () => {
    const entry = { id: "1", tenantId: "t", namespace: "ns", key: "k", value: { x: 1 }, version: 2, createdAt: "", updatedAt: "" };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: sseStream([{ event: "updated", data: JSON.stringify(entry) }]),
    }));

    const stream = openContextStream("http://test.local/v1/context/ns/k/subscribe", "crwl_key");
    const received: unknown[] = [];
    stream.on("updated", (e) => received.push(e));

    // Wait for the async SSE processing to complete
    await new Promise<void>((resolve) => {
      stream.on("close", () => resolve());
    });

    expect(received).toHaveLength(1);
    expect(received[0]).toMatchObject({ key: "k", value: { x: 1 } });
  });

  it("emits 'deleted' events", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: sseStream([{ event: "deleted", data: JSON.stringify({ key: "k" }) }]),
    }));

    const stream = openContextStream("http://test.local/v1/context/ns/k/subscribe", "crwl_key");
    const deleted: unknown[] = [];
    stream.on("deleted", (e) => deleted.push(e));

    await new Promise<void>((resolve) => stream.on("close", () => resolve()));
    expect(deleted).toHaveLength(1);
    expect(deleted[0]).toEqual({ key: "k" });
  });

  it("emits 'error' when fetch fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network error")));

    const stream = openContextStream("http://test.local/v1/context/ns/k/subscribe", "crwl_key");
    const errors: Error[] = [];
    stream.on("error", (e) => errors.push(e));

    await new Promise<void>((resolve) => stream.on("close", () => resolve()));
    expect(errors).toHaveLength(1);
    expect(errors[0]?.message).toBe("network error");
  });

  it("does not emit 'error' on AbortError (clean close)", async () => {
    const abortErr = new DOMException("aborted", "AbortError");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(abortErr));

    const stream = openContextStream("http://test.local/v1/context/ns/k/subscribe", "crwl_key");
    const errors: Error[] = [];
    stream.on("error", (e) => errors.push(e));

    await new Promise<void>((resolve) => stream.on("close", () => resolve()));
    expect(errors).toHaveLength(0);
  });

  it("sends X-API-Key header", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: sseStream([]),
    }));

    openContextStream("http://test.local/v1/context/ns/k/subscribe", "crwl_secret");

    await new Promise((r) => setTimeout(r, 10));
    const call = vi.mocked(fetch).mock.calls[0];
    expect((call?.[1] as RequestInit | undefined)?.headers).toMatchObject({ "X-API-Key": "crwl_secret" });
  });
});
