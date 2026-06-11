export class CrewLayerError extends Error {
  readonly status: number | undefined;
  readonly body: unknown;

  constructor(message: string, options?: { status?: number; body?: unknown }) {
    super(message);
    this.name = "CrewLayerError";
    this.status = options?.status;
    this.body = options?.body;
  }
}

export class AuthError extends CrewLayerError {
  constructor(message = "Unauthorized", options?: { status?: number; body?: unknown }) {
    super(message, { status: options?.status ?? 401, body: options?.body });
    this.name = "AuthError";
  }
}

export class NotFoundError extends CrewLayerError {
  constructor(message = "Not found", options?: { body?: unknown }) {
    super(message, { status: 404, body: options?.body });
    this.name = "NotFoundError";
  }
}

export class ConflictError extends CrewLayerError {
  constructor(message = "Conflict", options?: { body?: unknown }) {
    super(message, { status: 409, body: options?.body });
    this.name = "ConflictError";
  }
}

export class RateLimitError extends CrewLayerError {
  constructor(message = "Rate limit exceeded", options?: { body?: unknown }) {
    super(message, { status: 429, body: options?.body });
    this.name = "RateLimitError";
  }
}

export class ServerError extends CrewLayerError {
  constructor(message = "Internal server error", options?: { status?: number; body?: unknown }) {
    super(message, { status: options?.status ?? 500, body: options?.body });
    this.name = "ServerError";
  }
}

export async function throwIfError(response: Response): Promise<void> {
  if (response.ok) return;

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = await response.text().catch(() => undefined);
  }

  const detail =
    typeof body === "object" && body !== null && "detail" in body
      ? String((body as Record<string, unknown>)["detail"])
      : `HTTP ${response.status}`;

  if (response.status === 401 || response.status === 403) {
    throw new AuthError(detail, { status: response.status, body });
  }
  if (response.status === 404) {
    throw new NotFoundError(detail, { body });
  }
  if (response.status === 409) {
    throw new ConflictError(detail, { body });
  }
  if (response.status === 429) {
    throw new RateLimitError(detail, { body });
  }
  if (response.status >= 500) {
    throw new ServerError(detail, { status: response.status, body });
  }

  throw new CrewLayerError(detail, { status: response.status, body });
}
