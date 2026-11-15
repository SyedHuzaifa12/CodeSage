/**
 * Session lifecycle: make sure there is a usable access token, renewing or
 * creating a guest session when there isn't (ADR-027).
 *
 * Three guarantees worth knowing:
 *  - Single flight: concurrent requests that all find an expired token share
 *    ONE renewal, instead of each spending the (single-use) refresh token.
 *  - Cross-tab safety: renewal runs under a Web Lock and re-reads storage
 *    inside it, so two tabs never both rotate the same refresh token (the
 *    server treats a replayed token as theft and revokes the session).
 *  - Never silently downgrades on a transient failure: only a definitive 401
 *    from the refresh endpoint falls back to a fresh guest; a network error
 *    just propagates.
 */
import { ApiError, sendRequest } from "@/lib/api/http";
import { clearSession, getSession, readSessionFresh, setSession, type StoredSession } from "@/lib/auth/session";
import { getTurnstileToken } from "@/lib/auth/turnstile";
import type { AuthSessionData } from "@/lib/types/auth";

/** Renew this long before the access token actually expires, to absorb clock skew and request latency. */
const RENEW_SKEW_MS = 30_000;

let inflight: Promise<StoredSession> | null = null;

function isFresh(session: StoredSession): boolean {
  return session.accessExpiresAt - Date.now() > RENEW_SKEW_MS;
}

/** Persist the tokens from any auth response and return the stored form. */
export function storeAuthSession(data: AuthSessionData): StoredSession {
  const session: StoredSession = {
    accessToken: data.tokens.access_token,
    accessExpiresAt: Date.now() + data.tokens.expires_in * 1000,
    refreshToken: data.tokens.refresh_token,
  };
  setSession(session);
  return session;
}

function withCrossTabLock<T>(task: () => Promise<T>): Promise<T> {
  if (typeof navigator !== "undefined" && navigator.locks) {
    // lib.dom types the result as Promise<Promise<T>>; at runtime request() resolves with the awaited value.
    return navigator.locks.request("codesage-session-renew", task) as unknown as Promise<T>;
  }
  return task();
}

async function renew(failedAccessToken?: string): Promise<StoredSession> {
  // Another tab (or an earlier call) may already have renewed while we waited for the lock.
  const current = readSessionFresh();
  if (current && isFresh(current) && current.accessToken !== failedAccessToken) return current;

  if (current?.refreshToken) {
    try {
      const data = await sendRequest<AuthSessionData>("/auth/refresh", {
        method: "POST",
        body: { refresh_token: current.refreshToken },
      });
      return storeAuthSession(data);
    } catch (err) {
      if (!(err instanceof ApiError) || err.status !== 401) throw err;
      // Rejected. If someone else rotated the token in the meantime, theirs is the live one.
      const latest = readSessionFresh();
      if (latest && latest.refreshToken !== current.refreshToken && isFresh(latest)) return latest;
      clearSession();
    }
  }

  const turnstileToken = await getTurnstileToken();
  const data = await sendRequest<AuthSessionData>("/auth/guest", {
    method: "POST",
    body: { turnstile_token: turnstileToken },
  });
  return storeAuthSession(data);
}

/** Renew (or create) the session. Concurrent callers share one in-flight renewal. */
export function renewSession(failedAccessToken?: string): Promise<StoredSession> {
  if (!inflight) {
    inflight = withCrossTabLock(() => renew(failedAccessToken)).finally(() => {
      inflight = null;
    });
  }
  return inflight;
}

/** A session whose access token is valid for at least the next few seconds. */
export async function ensureSession(): Promise<StoredSession> {
  const session = getSession();
  if (session && isFresh(session)) return session;
  return renewSession();
}

/** Forget the session locally right away, then best-effort revoke it on the server. */
export async function endSession(): Promise<void> {
  const session = readSessionFresh();
  clearSession();
  if (!session) return;
  try {
    await sendRequest("/auth/logout", { method: "POST", body: { refresh_token: session.refreshToken } });
  } catch {
    /* already signed out locally; the server-side token simply expires */
  }
}
