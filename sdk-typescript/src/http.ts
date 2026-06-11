import { throwIfError, ServerError } from "./errors.js";

const RETRY_ON = new Set([500, 502, 503, 504]);
const MAX_RETRIES = 3;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export interface RequestOptions {
  params?: Record<string, string | number | boolean | undefined | null>;
  body?: unknown;
  signal?: AbortSignal;
  /** Skip JSON Content-Type header (e.g. for streaming requests). */
  raw?: boolean;
}

export class HttpClient {
  readonly baseUrl: string;
  readonly apiKey: string;
  private readonly maxRetries: number;
  private readonly timeout: number;

  constructor(options: {
    baseUrl: string;
    apiKey: string;
    maxRetries?: number;
    timeout?: number;
  }) {
    this.baseUrl = options.baseUrl.replace(/\/$/, "");
    this.apiKey = options.apiKey;
    this.maxRetries = options.maxRetries ?? MAX_RETRIES;
    this.timeout = options.timeout ?? 30_000;
  }

  private buildUrl(path: string, params?: RequestOptions["params"]): string {
    const url = `${this.baseUrl}${path}`;
    if (!params) return url;

    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null) {
        qs.set(k, String(v));
      }
    }
    const str = qs.toString();
    return str ? `${url}?${str}` : url;
  }

  async request<T = unknown>(
    method: string,
    path: string,
    options?: RequestOptions
  ): Promise<T> {
    const url = this.buildUrl(path, options?.params);
    const headers: Record<string, string> = {
      "X-API-Key": this.apiKey,
    };
    if (!options?.raw && options?.body !== undefined) {
      headers["Content-Type"] = "application/json";
    }

    const init: RequestInit = {
      method,
      headers,
    };
    if (options?.body !== undefined) {
      init.body = JSON.stringify(options.body);
    }

    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      if (attempt > 0) {
        await sleep(2 ** (attempt - 1) * 1000);
      }

      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.timeout);

      const signal = options?.signal
        ? abortEither(options.signal, controller.signal)
        : controller.signal;

      try {
        const response = await fetch(url, { ...init, signal });
        clearTimeout(timer);

        if (RETRY_ON.has(response.status) && attempt < this.maxRetries) {
          continue;
        }

        await throwIfError(response);

        if (response.status === 204) return undefined as T;
        return (await response.json()) as T;
      } catch (err) {
        clearTimeout(timer);
        const isAbort =
          err instanceof Error && err.name === "AbortError";

        if (isAbort || attempt >= this.maxRetries) {
          throw err;
        }

        // Network error — retry
        if (!(err instanceof Error && "status" in err)) {
          continue;
        }
        throw err;
      }
    }

    throw new ServerError("Max retries exceeded");
  }

  /** Returns the raw Response for streaming (SSE). No retry. */
  async stream(path: string, options?: Omit<RequestOptions, "body">): Promise<Response> {
    const url = this.buildUrl(path, options?.params);
    const response = await fetch(url, {
      method: "GET",
      headers: {
        "X-API-Key": this.apiKey,
        Accept: "text/event-stream",
      },
      signal: options?.signal,
    });

    await throwIfError(response);
    return response;
  }

  get<T = unknown>(path: string, options?: Omit<RequestOptions, "body">): Promise<T> {
    return this.request<T>("GET", path, options);
  }

  post<T = unknown>(path: string, body?: unknown, options?: Omit<RequestOptions, "body">): Promise<T> {
    return this.request<T>("POST", path, { ...options, body });
  }

  put<T = unknown>(path: string, body?: unknown, options?: Omit<RequestOptions, "body">): Promise<T> {
    return this.request<T>("PUT", path, { ...options, body });
  }

  patch<T = unknown>(path: string, body?: unknown, options?: Omit<RequestOptions, "body">): Promise<T> {
    return this.request<T>("PATCH", path, { ...options, body });
  }

  delete<T = unknown>(path: string, options?: Omit<RequestOptions, "body">): Promise<T> {
    return this.request<T>("DELETE", path, options);
  }
}

function abortEither(a: AbortSignal, b: AbortSignal): AbortSignal {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (a.aborted || b.aborted) {
    controller.abort();
  } else {
    a.addEventListener("abort", abort, { once: true });
    b.addEventListener("abort", abort, { once: true });
  }
  return controller.signal;
}
