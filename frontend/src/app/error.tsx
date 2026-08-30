"use client";

import { useEffect } from "react";
import { ErrorPanel } from "@/components/state/StateVocabulary";

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="flex min-h-screen items-center justify-center p-8">
      <ErrorPanel message="Something went wrong rendering this page." onRetry={reset} className="max-w-[420px]" />
    </div>
  );
}
