import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest, ApiError } from "@/lib/api/client";
import { endSession } from "@/lib/auth/authFlow";
import { authEvents } from "@/lib/auth/events";
import { clearSession, getSession, resetSessionCacheForTests, setSession } from "@/lib/auth/session";

type Handler = (init: RequestInit | undefined) => unknown;

function ok(data: unknown) {
  return { ok: true, status: 200, json: () => Promise.resolve({ success: true, message: "ok", data }) };
}

function fail(status: number, message: string, errors: unknown[] = []) {
  return { ok: false, status, json: () => Promise.resolve({ success: false, message, errors }) };
}

function sessionPayload(access: string, refresh: string, expiresIn = 900) {
  return {
    tokens: { access_token: access, token_type: "bearer", expires_in: expiresIn, refresh_token: refresh },
    user: { id: "u1", kind: "guest", github_login: null, display_name: null, avatar_url: null, is_admin: false, guest_expires_at: null },
    quota: { repositories_used: 0, repositories_limit: 1, questions_used_today: 0, questions_limit_daily: 15 },
  };
}

/** A fetch stub that routes by URL path and records every call. */
function stubFetch(routes: Record<string, Handler>) {
  const calls: { path: string; init: RequestInit | undefined }[] = [];
  const fn = vi.fn((url: string, init?: RequestInit) => {
    const path = new URL(url).pathname.replace("/api/v1", "");
    calls.push({ path, init });
    const handler = routes[path];
    if (!handler) throw new Error(`unrouted request: ${path}`);
    return Promise.resolve(handler(init));
  });
  vi.stubGlobal("fetch", fn);
  return { calls, count: (path: string) => calls.filter((c) => c.path === path).length };
}

const authHeader = (init: RequestInit | undefined) => (init?.headers as Record<string, string> | undefined)?.Authorization;

function seed(overrides: Partial<{ accessToken: string; accessExpiresAt: number; refreshToken: string }> = {}) {
  setSession({ accessToken: "access-1", accessExpiresAt: Date.now() + 3_600_000, refreshToken: "refresh-1", ...overrides });
}

beforeEach(() => {
  window.localStorage.clear();
  resetSessionCacheForTests();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("session bootstrap", () => {
  it("creates a guest session on first use, then sends its token", async () => {
    const http = stubFetch({
      "/auth/guest": () => ok(sessionPayload("guest-access", "guest-refresh")),
      "/repositories": () => ok({ repositories: [] }),
    });

    await apiRequest("/repositories");

    expect(http.count("/auth/guest")).toBe(1);
    expect(authHeader(http.calls[1].init)).toBe("Bearer guest-access");
    expect(getSession()?.refreshToken).toBe("guest-refresh"); // persisted for the next page load
  });

  it("reuses a stored session instead of creating a new guest", async () => {
    seed();
    const http = stubFetch({ "/repositories": () => ok({}) });
    await apiRequest("/repositories");
    expect(http.calls).toHaveLength(1);
    expect(authHeader(http.calls[0].init)).toBe("Bearer access-1");
  });

  it("sends no credentials, and creates no session, when auth is switched off", async () => {
    const http = stubFetch({ "/auth/github/authorize": () => ok({ authorize_url: "u", state: "s" }) });
    await apiRequest("/auth/github/authorize", { auth: false });
    expect(authHeader(http.calls[0].init)).toBeUndefined();
    expect(getSession()).toBeNull();
  });
});

describe("token renewal", () => {
  it("renews an access token that is about to expire before using it", async () => {
    seed({ accessExpiresAt: Date.now() + 5_000 }); // inside the 30s renewal skew
    const http = stubFetch({
      "/auth/refresh": () => ok(sessionPayload("access-2", "refresh-2")),
      "/repositories": () => ok({}),
    });
    await apiRequest("/repositories");
    expect(http.count("/auth/refresh")).toBe(1);
    expect(authHeader(http.calls[1].init)).toBe("Bearer access-2");
  });

  it("shares ONE renewal across concurrent requests (the refresh token is single-use)", async () => {
    seed({ accessExpiresAt: Date.now() - 1_000 });
    const http = stubFetch({
      "/auth/refresh": () => ok(sessionPayload("access-2", "refresh-2")),
      "/repositories": () => ok({}),
      "/auth/me": () => ok({}),
    });
    await Promise.all([apiRequest("/repositories"), apiRequest("/auth/me"), apiRequest("/repositories")]);
    expect(http.count("/auth/refresh")).toBe(1);
  });

  it("renews once and retries once when the server rejects a token it should have accepted", async () => {
    seed();
    let attempts = 0;
    const http = stubFetch({
      "/auth/refresh": () => ok(sessionPayload("access-2", "refresh-2")),
      "/repositories": (init) => {
        attempts += 1;
        return authHeader(init) === "Bearer access-2" ? ok({ fine: true }) : fail(401, "Access token expired.");
      },
    });
    await expect(apiRequest("/repositories")).resolves.toEqual({ fine: true });
    expect(attempts).toBe(2);
    expect(http.count("/auth/refresh")).toBe(1);
  });

  it("does not loop: a second 401 after renewing is surfaced to the caller", async () => {
    seed();
    const http = stubFetch({
      "/auth/refresh": () => ok(sessionPayload("access-2", "refresh-2")),
      "/repositories": () => fail(401, "Authentication required.", [{ code: "UNAUTHENTICATED" }]),
    });
    await expect(apiRequest("/repositories")).rejects.toMatchObject({ status: 401, code: "UNAUTHENTICATED" });
    expect(http.count("/repositories")).toBe(2);
    expect(http.count("/auth/refresh")).toBe(1);
  });

  it("falls back to a fresh guest only when the refresh token is definitively rejected", async () => {
    seed({ accessExpiresAt: Date.now() - 1_000 });
    const http = stubFetch({
      "/auth/refresh": () => fail(401, "Invalid refresh token.", [{ code: "UNAUTHENTICATED" }]),
      "/auth/guest": () => ok(sessionPayload("guest-access", "guest-refresh")),
      "/repositories": () => ok({}),
    });
    await apiRequest("/repositories");
    expect(http.count("/auth/guest")).toBe(1);
    expect(getSession()?.accessToken).toBe("guest-access");
  });

  it("never downgrades a signed-in user to a guest because of a network blip", async () => {
    seed({ accessExpiresAt: Date.now() - 1_000 });
    const http = stubFetch({ "/repositories": () => ok({}) });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    const error = await apiRequest("/repositories").catch((e) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).kind).toBe("network");
    expect(getSession()?.refreshToken).toBe("refresh-1"); // the session is untouched
    expect(http.calls).toHaveLength(0);
  });

  it("adopts a session another tab just renewed instead of replaying a spent refresh token", async () => {
    seed({ accessExpiresAt: Date.now() - 1_000 });
    stubFetch({
      "/auth/refresh": () => {
        // While our refresh was in flight, another tab rotated the token and stored a fresh session...
        window.localStorage.setItem(
          "codesage.session.v1",
          JSON.stringify({ accessToken: "tab2-access", accessExpiresAt: Date.now() + 600_000, refreshToken: "tab2-refresh" }),
        );
        // ...so the server rightly rejects our now-stale token.
        return fail(401, "Refresh token was just rotated; use the newest token.");
      },
      "/repositories": (init) => (authHeader(init) === "Bearer tab2-access" ? ok({ via: "tab2" }) : fail(401, "no")),
    });
    await expect(apiRequest("/repositories")).resolves.toEqual({ via: "tab2" });
  });
});

describe("guest limits", () => {
  it("tells the UI when a guest hits a limit that signing in lifts", async () => {
    seed();
    stubFetch({
      "/repositories": () => fail(403, "Guests can index one repository.", [{ code: "GUEST_QUOTA_EXCEEDED" }]),
    });
    const heard: string[] = [];
    const stop = authEvents.onQuotaExceeded((message) => heard.push(message));

    await expect(apiRequest("/repositories", { method: "POST", body: {} })).rejects.toMatchObject({ status: 403 });

    stop();
    expect(heard).toEqual(["Guests can index one repository."]);
  });

  it("does not raise the sign-in prompt for other errors", async () => {
    seed();
    stubFetch({ "/repositories": () => fail(429, "Daily limit.", [{ code: "RATE_LIMITED" }]) });
    const heard: string[] = [];
    const stop = authEvents.onQuotaExceeded((message) => heard.push(message));
    await apiRequest("/repositories").catch(() => undefined);
    stop();
    expect(heard).toEqual([]);
  });
});

describe("signing out", () => {
  it("forgets the session locally first, then revokes it on the server", async () => {
    seed();
    const http = stubFetch({ "/auth/logout": () => ok({}) });
    await endSession();
    expect(getSession()).toBeNull();
    expect(http.count("/auth/logout")).toBe(1);
    expect(JSON.parse(http.calls[0].init?.body as string)).toEqual({ refresh_token: "refresh-1" });
  });

  it("still signs out locally when the server is unreachable", async () => {
    seed();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    await expect(endSession()).resolves.toBeUndefined();
    expect(getSession()).toBeNull();
  });

  it("is a no-op without a session", async () => {
    clearSession();
    const http = stubFetch({});
    await endSession();
    expect(http.calls).toHaveLength(0);
  });
});
