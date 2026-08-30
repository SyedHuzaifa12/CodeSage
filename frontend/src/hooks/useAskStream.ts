"use client";

import { useCallback, useRef, useState } from "react";
import { aiApi } from "@/lib/api/ai";
import { ApiError } from "@/lib/api/client";
import { createSyntheticAnswerStream } from "@/lib/answerStream";
import type { RibbonStageKey } from "@/lib/reasoningRibbon";
import { RIBBON_STAGE_ORDER } from "@/lib/reasoningRibbon";
import type { StageState } from "@/components/devices/ReasoningRibbon";
import type { AskOptions, AskResponseData, Citation, VerificationInfo } from "@/lib/types/ai";

export interface AskTurn {
  id: string;
  question: string;
  answerText: string;
  citations: Citation[];
  verification: VerificationInfo | null;
  metadata: AskResponseData["metadata"] | null;
  stageStates: Record<RibbonStageKey, StageState>;
  status: "streaming" | "done" | "error";
  errorMessage?: string;
}

const IDLE_STAGES: Record<RibbonStageKey, StageState> = {
  retrieve: "pending",
  evidence: "pending",
  reason: "pending",
  verify: "pending",
};

/**
 * Drives the Ask page's UI purely from the AnswerStream contract
 * (Design System §13) — this hook is the ONLY place that knows the
 * backend is synchronous today; every component consuming `turns` would
 * work unchanged against a real streaming adapter.
 */
export function useAskStream(repositoryId: string) {
  const [turns, setTurns] = useState<AskTurn[]>([]);
  const cancelRef = useRef<(() => void) | null>(null);

  const ask = useCallback(
    (question: string, options?: AskOptions) => {
      const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      setTurns((prev) => [
        ...prev,
        {
          id,
          question,
          answerText: "",
          citations: [],
          verification: null,
          metadata: null,
          stageStates: { ...IDLE_STAGES, retrieve: "active" },
          status: "streaming",
        },
      ]);

      const update = (patch: Partial<AskTurn>) =>
        setTurns((prev) => prev.map((t) => (t.id === id ? { ...t, ...patch } : t)));

      // Approximates stage progression for the ribbon while the single
      // network call is in flight (retrieval -> evidence -> reasoning),
      // then reconciles with real stage_latency_ms once the response lands.
      const progressTimers = [
        setTimeout(() => update({ stageStates: { ...IDLE_STAGES, retrieve: "done", evidence: "active" } }), 350),
        setTimeout(() => update({ stageStates: { ...IDLE_STAGES, retrieve: "done", evidence: "done", reason: "active" } }), 900),
      ];

      const stream = createSyntheticAnswerStream(
        () => aiApi.ask(repositoryId, question, options),
        {
          onToken: (_tok, fullText) => update({ answerText: fullText }),
          onCitations: (citations) => update({ citations }),
          onVerification: (verification) =>
            update({
              verification,
              stageStates: { retrieve: "done", evidence: "done", reason: "done", verify: "active" },
            }),
          onDone: (full) => {
            progressTimers.forEach(clearTimeout);
            update({
              status: "done",
              metadata: full.metadata,
              stageStates: { retrieve: "done", evidence: "done", reason: "done", verify: "done" },
            });
          },
          onError: (err) => {
            progressTimers.forEach(clearTimeout);
            update({
              status: "error",
              errorMessage: err instanceof ApiError ? err.message : "Something went wrong answering this question.",
            });
          },
        },
      );

      cancelRef.current = stream.cancel;
      void stream.start();
    },
    [repositoryId],
  );

  const cancel = useCallback(() => {
    cancelRef.current?.();
  }, []);

  return { turns, ask, cancel };
}

export { RIBBON_STAGE_ORDER };
