import { ensureSession, renewSession } from "@/lib/auth/authFlow";
import { authEvents } from "@/lib/auth/events";
import { ApiError, sendRequest, type RequestOptions } from "@/lib/api/http";

export { API_BASE_URL, API_V1_PREFIX, ApiError } from "@/lib/api/http";
export type { RequestOptions } from "@/lib/api/http";

async function authorized<T>(path: string, options: RequestOptions): Promise<T> {
  if (options.auth === false) return sendRequest<T>(path, options);

  const session = await ensureSession();
  try {
    return await sendRequest<T>(path, options, session.accessToken);
  } catch (err) {
    if (!(err instanceof ApiError) || err.status !== 401) throw err;
    // The server rejected our token (expired early, account gone, ...): renew once and retry once.
    const renewed = await renewSession(session.accessToken);
    return sendRequest<T>(path, options, renewed.accessToken);
  }
}

/**
 * Typed fetch wrapper for the CodeSage API. Attaches the caller's session —
 * creating a guest session on first use and renewing it as needed — unwraps
 * the {success,message,data} envelope, and throws a normalized ApiError for
 * everything else. A guest hitting a limit that signing in lifts also
 * notifies the UI so it can offer the sign-in prompt.
 */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  try {
    return await authorized<T>(path, options);
  } catch (err) {
    if (err instanceof ApiError && err.code === "GUEST_QUOTA_EXCEEDED") {
      authEvents.emitQuotaExceeded(err.message);
    }
    throw err;
  }
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
