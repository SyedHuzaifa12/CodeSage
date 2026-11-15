"use client";

import { useQueryClient } from "@tanstack/react-query";
import { usePathname } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { SignInModal } from "@/components/auth/SignInModal";
import { authApi } from "@/lib/api/auth";
import { endSession } from "@/lib/auth/authFlow";
import { authEvents } from "@/lib/auth/events";
import { saveReturnTo } from "@/lib/auth/returnTo";
import { subscribeSession } from "@/lib/auth/session";
import { queryKeys } from "@/lib/query/keys";
import { useMe } from "@/lib/query/auth";
import type { AuthUser, QuotaStatus } from "@/lib/types/auth";

interface AuthContextValue {
  status: "loading" | "ready" | "error";
  error: unknown;
  user: AuthUser | undefined;
  quota: QuotaStatus | undefined;
  isGuest: boolean;
  isAdmin: boolean;
  /** Start GitHub login. Redirects away on success; rejects (e.g. login not configured) so the caller can show why. */
  signIn: (opts?: { returnTo?: string }) => Promise<void>;
  signOut: () => Promise<void>;
  /** Open the sign-in dialog, optionally with the reason (e.g. the quota message). */
  openSignIn: (reason?: string) => void;
  refetch: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const CALLBACK_PATH = "/auth/callback";

/**
 * Owns "who is using the app": bootstraps the session, exposes the user and
 * their quota, and hosts the sign-in dialog — including opening it
 * automatically whenever a guest hits a limit that signing in lifts.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const pathname = usePathname();
  // The OAuth callback replaces the session; bootstrapping a guest first would be wasted (and bot-checked).
  const me = useMe(!pathname.startsWith(CALLBACK_PATH));
  const [dialog, setDialog] = useState<{ open: boolean; reason?: string }>({ open: false });

  useEffect(
    () =>
      authEvents.onQuotaExceeded((message) => {
        setDialog({ open: true, reason: message });
        void client.invalidateQueries({ queryKey: queryKeys.me() });
      }),
    [client],
  );

  // Another tab signed in/out or renewed: re-check who we are.
  useEffect(
    () =>
      subscribeSession(({ external }) => {
        if (external) void client.invalidateQueries({ queryKey: queryKeys.me() });
      }),
    [client],
  );

  // If the identity itself changed (not just a token renewal), nothing cached for the old one may linger.
  const userId = me.data?.user.id;
  const previousUserId = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (!userId) return;
    if (previousUserId.current && previousUserId.current !== userId) {
      client.removeQueries({ predicate: (query) => query.queryKey[0] !== "me" });
      void client.invalidateQueries();
    }
    previousUserId.current = userId;
  }, [userId, client]);

  const signIn = useCallback(async (opts?: { returnTo?: string }) => {
    const { authorize_url: url } = await authApi.githubAuthorize();
    saveReturnTo(opts?.returnTo ?? `${window.location.pathname}${window.location.search}`);
    window.location.assign(url);
  }, []);

  const signOut = useCallback(async () => {
    await endSession();
    window.location.assign("/"); // a full reload also drops every in-memory cache from the old identity
  }, []);

  const openSignIn = useCallback((reason?: string) => setDialog({ open: true, reason }), []);

  const value = useMemo<AuthContextValue>(() => {
    const status = me.isError ? "error" : me.data ? "ready" : "loading";
    return {
      status,
      error: me.error,
      user: me.data?.user,
      quota: me.data?.quota,
      isGuest: me.data?.user.kind === "guest",
      isAdmin: me.data?.user.is_admin ?? false,
      signIn,
      signOut,
      openSignIn,
      refetch: () => void me.refetch(),
    };
  }, [me, signIn, signOut, openSignIn]);

  return (
    <AuthContext.Provider value={value}>
      {children}
      <SignInModal
        open={dialog.open}
        reason={dialog.reason}
        onClose={() => setDialog({ open: false })}
        onSignIn={() => signIn()}
      />
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
