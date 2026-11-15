/**
 * Persistent session store (ADR-027).
 *
 * The refresh token lives in localStorage — not an httpOnly cookie —
 * because the frontend and API are on different registrable domains on
 * free hosting, where browsers block cross-site cookies. That makes it
 * readable by any XSS, so it is mitigated server-side instead: refresh
 * tokens rotate on every use and a replayed one revokes the whole session.
 * The short-lived access token is stored alongside it so several tabs share
 * one session instead of each minting their own; that adds no exposure
 * beyond the refresh token.
 *
 * SSR-safe: every browser API is guarded, and a missing/blocked
 * localStorage degrades to an in-memory session for the current page.
 */

export interface StoredSession {
  accessToken: string;
  /** Epoch milliseconds. */
  accessExpiresAt: number;
  refreshToken: string;
}

export interface SessionChange {
  /** True when the change came from another browser tab. */
  external: boolean;
}

const STORAGE_KEY = "codesage.session.v1";

let cache: StoredSession | null | undefined; // undefined = not read from storage yet
const listeners = new Set<(change: SessionChange) => void>();
let storageListenerInstalled = false;

function parse(raw: string | null): StoredSession | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<StoredSession>;
    if (
      typeof value.accessToken === "string" &&
      typeof value.accessExpiresAt === "number" &&
      typeof value.refreshToken === "string"
    ) {
      return { accessToken: value.accessToken, accessExpiresAt: value.accessExpiresAt, refreshToken: value.refreshToken };
    }
  } catch {
    /* corrupt entry: treat as no session */
  }
  return null;
}

/** The stored session, `null` if storage is readable but empty, `undefined` if storage is unavailable. */
function readStorage(): StoredSession | null | undefined {
  try {
    return parse(window.localStorage.getItem(STORAGE_KEY));
  } catch {
    return undefined; // storage blocked (private mode, policy)
  }
}

function emit(change: SessionChange): void {
  listeners.forEach((listener) => listener(change));
}

function installStorageListener(): void {
  if (storageListenerInstalled || typeof window === "undefined") return;
  storageListenerInstalled = true;
  window.addEventListener("storage", (event) => {
    if (event.key === STORAGE_KEY || event.key === null) {
      cache = readStorage() ?? null;
      emit({ external: true });
    }
  });
}

/** The current session from memory (loading it from storage on first use). */
export function getSession(): StoredSession | null {
  if (typeof window === "undefined") return null;
  if (cache === undefined) cache = readStorage() ?? null;
  return cache;
}

/**
 * Re-reads storage, bypassing the in-memory copy — use inside a lock, where
 * another tab may have just written (or signed out). Only when storage is
 * unavailable does the in-memory copy remain the source of truth.
 */
export function readSessionFresh(): StoredSession | null {
  if (typeof window === "undefined") return null;
  const stored = readStorage();
  if (stored !== undefined) cache = stored;
  return cache ?? null;
}

export function setSession(session: StoredSession): void {
  cache = session;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
  } catch {
    /* in-memory only */
  }
  emit({ external: false });
}

export function clearSession(): void {
  cache = null;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* nothing to do */
  }
  emit({ external: false });
}

export function subscribeSession(listener: (change: SessionChange) => void): () => void {
  installStorageListener();
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Test helper: forget the in-memory copy so the next read goes to storage. */
export function resetSessionCacheForTests(): void {
  cache = undefined;
}
