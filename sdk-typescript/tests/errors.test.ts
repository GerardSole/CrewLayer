import { describe, it, expect, vi, afterEach } from "vitest";
import {
  CrewLayerError,
  AuthError,
  NotFoundError,
  ConflictError,
  RateLimitError,
  ServerError,
  throwIfError,
} from "../src/errors.js";

afterEach(() => vi.unstubAllGlobals());

function makeResponse(status: number, body: unknown): Response {
  return {
    ok: status < 400,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response;
}

describe("error classes", () => {
  it("CrewLayerError stores status and body", () => {
    const err = new CrewLayerError("msg", { status: 422, body: { detail: "bad" } });
    expect(err.status).toBe(422);
    expect(err.body).toEqual({ detail: "bad" });
    expect(err.name).toBe("CrewLayerError");
  });

  it("AuthError defaults to 401", () => {
    const err = new AuthError();
    expect(err.status).toBe(401);
    expect(err.name).toBe("AuthError");
    expect(err).toBeInstanceOf(CrewLayerError);
  });

  it("NotFoundError is 404", () => {
    const err = new NotFoundError("missing");
    expect(err.status).toBe(404);
    expect(err.name).toBe("NotFoundError");
  });

  it("ConflictError is 409", () => {
    const err = new ConflictError();
    expect(err.status).toBe(409);
    expect(err.name).toBe("ConflictError");
  });

  it("RateLimitError is 429", () => {
    const err = new RateLimitError();
    expect(err.status).toBe(429);
    expect(err.name).toBe("RateLimitError");
  });

  it("ServerError defaults to 500", () => {
    const err = new ServerError();
    expect(err.status).toBe(500);
    expect(err.name).toBe("ServerError");
  });
});

describe("throwIfError", () => {
  it("does nothing on 200", async () => {
    await expect(throwIfError(makeResponse(200, {}))).resolves.toBeUndefined();
  });

  it("throws AuthError on 401", async () => {
    await expect(throwIfError(makeResponse(401, { detail: "bad key" }))).rejects.toBeInstanceOf(AuthError);
  });

  it("throws AuthError on 403", async () => {
    await expect(throwIfError(makeResponse(403, { detail: "forbidden" }))).rejects.toBeInstanceOf(AuthError);
  });

  it("throws NotFoundError on 404", async () => {
    await expect(throwIfError(makeResponse(404, { detail: "not found" }))).rejects.toBeInstanceOf(NotFoundError);
  });

  it("throws ConflictError on 409", async () => {
    await expect(throwIfError(makeResponse(409, { detail: "conflict" }))).rejects.toBeInstanceOf(ConflictError);
  });

  it("throws RateLimitError on 429", async () => {
    await expect(throwIfError(makeResponse(429, {}))).rejects.toBeInstanceOf(RateLimitError);
  });

  it("throws ServerError on 500", async () => {
    await expect(throwIfError(makeResponse(500, {}))).rejects.toBeInstanceOf(ServerError);
  });

  it("throws ServerError on 503", async () => {
    await expect(throwIfError(makeResponse(503, {}))).rejects.toBeInstanceOf(ServerError);
  });

  it("extracts detail field from body", async () => {
    try {
      await throwIfError(makeResponse(404, { detail: "agent not found" }));
    } catch (err) {
      expect((err as Error).message).toBe("agent not found");
    }
  });
});
