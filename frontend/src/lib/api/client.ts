import type { ApiEnvelope, ErrorDetail } from "@/lib/types/envelope";

/**
 * The single public env var this app reads. Never a secret — the FastAPI
 * backend (with its Groq/DB/Redis/Qdrant credentials) stays off Vercel
 * entirely (Design System §14.4).
 */
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/+$/, "") ?? "http://localhost:8000";

export const API_V1_PREFIX = "/api/v1";

/** Thrown for both HTTP-level failures and network/timeout failures. */
export class ApiError extends Error {
  readonly status: number;
  readonly errors: ErrorDetail[];
  readonly kind: "http" | "network" | "timeout";

  constructor(message: string, opts: { status?: number; errors?: ErrorDetail[]; kind?: ApiError["kind"] } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = opts.status ?? 0;
    this.errors = opts.errors ?? [];
    this.kind = opts.kind ?? "http";
  }
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  signal?: AbortSignal;
  timeoutMs?: number;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = new URL(`${API_BASE_URL}${API_V1_PREFIX}${path}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

/**
 * Typed fetch wrapper that unwraps the backend's {success,message,data}
 * envelope and throws a normalized ApiError for every other case
 * (network failure, timeout, or the {success:false,message,errors} shape).
 */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query, signal, timeoutMs = 30_000 } = options;

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  if (signal) {
    signal.addEventListener("abort", () => controller.abort());
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
      cache: "no-store",
    });
  } catch (err) {
    clearTimeout(timeout);
    if ((err as Error).name === "AbortError") {
      throw new ApiError("The request timed out or was cancelled.", { kind: "timeout" });
    }
    throw new ApiError("Couldn't reach the CodeSage backend. Check your connection and try again.", {
      kind: "network",
    });
  }
  clearTimeout(timeout);

  let json: ApiEnvelope<T> | undefined;
  try {
    json = (await response.json()) as ApiEnvelope<T>;
  } catch {
    if (!response.ok) {
      throw new ApiError(`Request failed with status ${response.status}.`, {
        status: response.status,
        kind: "http",
      });
    }
    throw new ApiError("The server returned an unexpected response.", { kind: "http", status: response.status });
  }

  if (!json.success) {
    throw new ApiError(json.message || "The request failed.", {
      status: response.status,
      errors: json.errors ?? [],
      kind: "http",
    });
  }

  return json.data;
}

export const api = {
  get: <T>(path: string, options?: Omit<RequestOptions, "method" | "body">) =>
    apiRequest<T>(path, { ...options, method: "GET" }),
  post: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, "method" | "body">) =>
    apiRequest<T>(path, { ...options, method: "POST", body }),
  patch: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, "method" | "body">) =>
    apiRequest<T>(path, { ...options, method: "PATCH", body }),
  delete: <T>(path: string, options?: Omit<RequestOptions, "method" | "body">) =>
    apiRequest<T>(path, { ...options, method: "DELETE" }),
};
