"use client";

import { useAuth } from "@/context/AuthContext";

/** Slim, honest reminder under the top bar while someone is using a guest session: what's left, and how to get more. */
export function GuestBanner() {
  const { status, isGuest, quota, openSignIn } = useAuth();
  if (status !== "ready" || !isGuest || !quota) return null;

  const reposLeft = Math.max(0, quota.repositories_limit - quota.repositories_used);
  const questionsLeft = Math.max(0, quota.questions_limit_daily - quota.questions_used_today);

  return (
    <div
      role="status"
      className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 border-b border-border-subtle bg-surface-2 px-4 py-1.5 text-[12.5px] text-text-secondary"
    >
      <span>
        Guest session ·{" "}
        <b className="font-semibold text-text-primary">
          {reposLeft} of {quota.repositories_limit}
        </b>{" "}
        free {quota.repositories_limit === 1 ? "repository" : "repositories"} left ·{" "}
        <b className="font-semibold text-text-primary">{questionsLeft}</b> questions left today
      </span>
      <button type="button" className="cs-link" onClick={() => openSignIn()}>
        Sign in with GitHub to keep your work
      </button>
    </div>
  );
}
