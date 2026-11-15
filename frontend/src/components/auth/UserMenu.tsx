"use client";

import { LogOut } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { useAuth } from "@/context/AuthContext";

/** Top-bar identity: a Sign-in button for guests; avatar and Sign-out for members. */
export function UserMenu() {
  const { status, user, isGuest, openSignIn, signOut } = useAuth();

  if (status !== "ready" || !user) {
    return <span className="hidden h-7 w-7 rounded-full bg-surface-3 sm:block" aria-hidden="true" />;
  }
  if (isGuest) {
    return (
      <Button size="sm" variant="secondary" onClick={() => openSignIn()}>
        Sign in
      </Button>
    );
  }

  const label = user.github_login ? `@${user.github_login}` : (user.display_name ?? "Signed in");
  return (
    <div className="flex items-center gap-1">
      {user.avatar_url ? (
        // eslint-disable-next-line @next/next/no-img-element -- a remote GitHub avatar; next/image would need a domain allow-list for one 28px icon
        <img src={user.avatar_url} alt="" title={label} width={28} height={28} className="h-7 w-7 rounded-full border border-border-subtle" />
      ) : (
        <span
          title={label}
          className="grid h-7 w-7 place-items-center rounded-full border border-border-subtle bg-surface-3 font-mono text-[10px] uppercase text-text-secondary"
        >
          {label.replace("@", "").slice(0, 2)}
        </span>
      )}
      <button
        type="button"
        onClick={() => void signOut()}
        aria-label={`Sign out ${label}`}
        title="Sign out"
        className="grid h-8 w-8 place-items-center rounded-[8px] text-text-tertiary transition-colors hover:bg-surface-2 hover:text-text-primary"
      >
        <LogOut size={15} strokeWidth={1.6} aria-hidden="true" />
      </button>
    </div>
  );
}
