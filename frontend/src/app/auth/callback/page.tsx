"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { TopologyMark } from "@/components/devices/TopologyMark";
import { Notice } from "@/components/state/StateVocabulary";
import { authApi } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";
import { storeAuthSession } from "@/lib/auth/authFlow";
import { consumeReturnTo } from "@/lib/auth/returnTo";
import { getSession } from "@/lib/auth/session";

type Phase = { name: "working" } | { name: "done"; transferred: number } | { name: "error"; message: string };

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === "OAUTH_FAILED") return err.message;
    if (err.code === "SERVICE_UNAVAILABLE") return "GitHub sign-in isn't available right now. Please try again shortly.";
    return err.message;
  }
  return "Something went wrong while signing you in.";
}

function CallbackInner() {
  const params = useSearchParams();
  const router = useRouter();
  const client = useQueryClient();
  const [phase, setPhase] = useState<Phase>({ name: "working" });
  // The authorization code is single-use: guard against React StrictMode's double effect and re-renders.
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    const code = params.get("code");
    const state = params.get("state");
    const githubError = params.get("error");

    if (githubError) {
      setPhase({
        name: "error",
        message: githubError === "access_denied" ? "You cancelled the GitHub sign-in." : `GitHub reported: ${githubError}.`,
      });
      return;
    }
    if (!code || !state) {
      setPhase({ name: "error", message: "This sign-in link is incomplete. Please start again." });
      return;
    }

    // A page refresh would replay a spent code; if we already handled this state, just go home.
    const handledKey = `codesage.oauth.handled.${state}`;
    try {
      if (window.sessionStorage.getItem(handledKey)) {
        router.replace("/");
        return;
      }
      window.sessionStorage.setItem(handledKey, "1");
    } catch {
      /* storage blocked: proceed without the replay guard */
    }

    // With a guest session, send it so the backend upgrades that guest in place and keeps their repository.
    authApi
      .githubLogin(code, state, Boolean(getSession()))
      .then((data) => {
        storeAuthSession(data);
        client.clear(); // everything cached belonged to the previous identity
        setPhase({ name: "done", transferred: data.repositories_transferred });
        setTimeout(() => router.replace(consumeReturnTo()), data.repositories_transferred > 0 ? 1800 : 400);
      })
      .catch((err) => setPhase({ name: "error", message: describeError(err) }));
  }, [params, router, client]);

  return (
    <div className="cs-page cs-page-glow min-h-dvh">
      <div className="mx-auto flex max-w-[520px] flex-col items-start gap-5 px-6 pt-24">
        <TopologyMark variant="mark" size={30} />
        {phase.name === "working" && (
          <>
            <h1 className="cs-masthead">Signing you in…</h1>
            <span className="cs-indet w-[140px]" aria-hidden="true" />
            <p className="cs-lede">Finishing up with GitHub.</p>
          </>
        )}
        {phase.name === "done" && (
          <>
            <h1 className="cs-masthead">You&rsquo;re in.</h1>
            <p className="cs-lede" role="status">
              {phase.transferred > 0
                ? `Moved ${phase.transferred} ${phase.transferred === 1 ? "repository" : "repositories"} from your guest session into your account.`
                : "Taking you back…"}
            </p>
          </>
        )}
        {phase.name === "error" && (
          <>
            <h1 className="cs-masthead">Couldn&rsquo;t sign in</h1>
            <Notice tone="bad" title="Sign-in didn't complete">
              {phase.message}
            </Notice>
            <Link href="/" className="cs-link">
              Back to CodeSage
            </Link>
          </>
        )}
      </div>
    </div>
  );
}

export default function AuthCallbackPage() {
  return (
    <Suspense fallback={null}>
      <CallbackInner />
    </Suspense>
  );
}
