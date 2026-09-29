"use client";

import { useCallback, useSyncExternalStore } from "react";
import { aiApi } from "@/lib/api/ai";
import { createSyntheticAnswerStream, type AnswerStream } from "@/lib/answerStream";
import { askSession, type AskTurn } from "@/lib/askSession";
import type { AskOptions } from "@/lib/types/ai";

export type { AskTurn } from "@/lib/askSession";

const activeStreams = new Map<string, AnswerStream>();

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

/**
 * Drives the Ask page purely from the AnswerStream contract (Design System
 * §13). This hook is the ONLY place that knows the backend is synchronous
 * today: `createSyntheticAnswerStream` reveals the complete `/ask` answer
 * client-side, and a real SSE adapter can replace it without touching any
 * component that renders `turns`.
 */
export function useAskStream(repositoryId: string) {
  const turns = useSyncExternalStore(
    askSession.subscribe,
    () => askSession.get(repositoryId),
    () => askSession.get(repositoryId),
  );

  const ask = useCallback(
    (question: string, options?: AskOptions, replaceId?: string) => {
      const id = replaceId ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      const turn: AskTurn = {
        id,
        question,
        stage: 0,
        status: "thinking",
        partial: "",
        response: null,
        error: null,
        askedAt: Date.now(),
      };
      const current = askSession.get(repositoryId);
      askSession.set(repositoryId, replaceId ? current.map((t) => (t.id === replaceId ? turn : t)) : [...current, turn]);
      const update = (patch: Partial<AskTurn>) => askSession.update(repositoryId, id, patch);

      // Client-paced stage progression while the single request is in
      // flight (retrieve -> evidence -> reason); real per-stage timings
      // replace this the moment the response lands.
      const timers = [
        setTimeout(() => update({ stage: 1 }), 350),
        setTimeout(() => update({ stage: 2 }), 900),
      ];
      const reduced = prefersReducedMotion();
      const stream = createSyntheticAnswerStream(
        () => aiApi.ask(repositoryId, question, options),
        {
          onVerification: () => {
            timers.forEach(clearTimeout);
            update({ stage: 3, status: "revealing" });
          },
          onToken: (_tok, soFar) => update({ partial: soFar }),
          onDone: (full) => {
            activeStreams.delete(id);
            update({ status: "done", stage: 4, response: full, partial: full.answer });
          },
          onError: (err) => {
            timers.forEach(clearTimeout);
            activeStreams.delete(id);
            update({ status: "error", error: err });
          },
        },
        { msPerToken: reduced ? 0 : 16, wordsPerToken: 2 },
      );
      activeStreams.set(id, stream);
      void stream.start();
      return id;
    },
    [repositoryId],
  );

  const cancel = useCallback((id: string) => {
    activeStreams.get(id)?.cancel();
    activeStreams.delete(id);
    askSession.update(repositoryId, id, { status: "error", error: new Error("Cancelled.") });
  }, [repositoryId]);

  const clear = useCallback(() => {
    activeStreams.forEach((s) => s.cancel());
    activeStreams.clear();
    askSession.clear(repositoryId);
  }, [repositoryId]);

  return { turns, ask, cancel, clear };
}
