"use client";

import { Github } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { ApiError } from "@/lib/api/client";

const BENEFITS = [
  "Keep the repository you already indexed",
  "Index more repositories",
  "A much higher daily question allowance",
];

function describe(err: unknown): string {
  if (err instanceof ApiError && err.code === "SERVICE_UNAVAILABLE") {
    return "GitHub sign-in isn't available on this server yet.";
  }
  return err instanceof Error ? err.message : "Couldn't start GitHub sign-in. Please try again.";
}

/** The one place guests are asked to sign in — opened manually or whenever a limit is hit. */
export function SignInModal({
  open,
  reason,
  onClose,
  onSignIn,
}: {
  open: boolean;
  reason?: string;
  onClose: () => void;
  onSignIn: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setBusy(false);
      setError(null);
    }
  }, [open]);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      await onSignIn(); // navigates away on success, so `busy` intentionally stays on
    } catch (err) {
      setError(describe(err));
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onOpenChange={(next) => !next && onClose()}
      title="Sign in to continue"
      description={reason ?? "You're using a guest session. Sign in with GitHub to do more."}
    >
      <ul className="space-y-1.5 text-small text-text-secondary">
        {BENEFITS.map((benefit) => (
          <li key={benefit} className="flex gap-2">
            <span className="text-violet" aria-hidden="true">
              ·
            </span>
            {benefit}
          </li>
        ))}
      </ul>
      <p className="mt-3 text-small text-text-tertiary">
        CodeSage only asks GitHub who you are (your public profile) — it never reads your repositories.
      </p>
      {error && (
        <p className="mt-3 text-small text-danger" role="alert">
          {error}
        </p>
      )}
      <div className="mt-6 flex justify-end gap-2.5">
        <Button variant="ghost" onClick={onClose}>
          Not now
        </Button>
        <Button variant="primary" loading={busy} onClick={start}>
          {!busy && <Github size={15} aria-hidden="true" />}
          Continue with GitHub
        </Button>
      </div>
    </Modal>
  );
}
