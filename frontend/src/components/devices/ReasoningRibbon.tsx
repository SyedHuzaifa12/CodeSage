"use client";

import { getConfidenceSpec } from "@/lib/confidence";
import { RIBBON_STAGE_LABELS, RIBBON_STAGE_ORDER, type RibbonStageKey } from "@/lib/reasoningRibbon";
import type { VerificationStatus } from "@/lib/types/ai";
import { cn } from "@/lib/utils";

export type StageState = "pending" | "active" | "done" | "skipped";

/**
 * Signature device #4 — Reasoning Ribbon (Design System §17-D): the AI
 * Engine's own pipeline made visible beside every answer. Four
 * reader-facing stages mapped from the real seven (lib/reasoningRibbon.ts);
 * once an answer lands each stage shows its real latency, "skipped" when
 * the pipeline declined before the LLM call, and the final dot takes the
 * verification colour.
 */
export function ReasoningRibbon({
  stageStates,
  stageMs,
  finalStatus,
  cached,
  orientation = "vertical",
  className,
}: {
  stageStates: Record<RibbonStageKey, StageState>;
  stageMs?: Partial<Record<RibbonStageKey, number>>;
  finalStatus?: VerificationStatus;
  cached?: boolean;
  orientation?: "vertical" | "horizontal";
  className?: string;
}) {
  const vertical = orientation === "vertical";
  const done = RIBBON_STAGE_ORDER.filter((k) => stageStates[k] === "done" || stageStates[k] === "skipped").length;
  return (
    <ol
      className={cn(
        "relative m-0 list-none p-0 before:absolute before:bg-[linear-gradient(180deg,oklch(1_0_0/0.2),oklch(1_0_0/0.04))]",
        vertical ? "flex flex-col gap-5 pt-1 before:bottom-3.5 before:left-[5px] before:top-3 before:w-px" : "flex flex-wrap gap-x-4 gap-y-2 before:left-1.5 before:right-1.5 before:top-1.5 before:h-px",
        className,
      )}
      aria-label={`Reasoning pipeline: ${done} of 4 stages complete${finalStatus ? `, verification ${getConfidenceSpec(finalStatus).label}` : ""}`}
    >
      {RIBBON_STAGE_ORDER.map((key) => {
        const state = stageStates[key];
        const final = key === "verify" && state === "done" && finalStatus ? `var(${getConfidenceSpec(finalStatus).colorVar})` : null;
        const ms = stageMs?.[key];
        const sub = state === "skipped" ? "skipped" : cached ? (key === "verify" ? "cached" : null) : ms !== undefined && state === "done" ? `${ms.toLocaleString("en-US")}ms` : null;
        return (
          <li key={key} className="relative grid grid-cols-[11px_auto] items-start gap-[9px]">
            <span
              aria-hidden="true"
              className={cn(
                "mt-0.5 h-[11px] w-[11px] rounded-full border-[1.5px] border-border-strong bg-bg transition-all duration-standard ease-cs",
                state === "active" && "cs-pulse border-violet bg-violet shadow-[0_0_0_4px_var(--cs-violet-tint),0_0_12px_oklch(0.75_0.13_300/0.55)]",
                state === "done" && !final && "border-[oklch(0.78_0.01_280)] bg-[oklch(0.78_0.01_280)]",
                state === "skipped" && "border-dashed bg-transparent",
              )}
              style={final ? { background: final, borderColor: final } : undefined}
            />
            <span
              className={cn(
                "font-mono text-[9.5px] font-medium uppercase leading-[1.3] tracking-[0.09em] text-text-tertiary transition-colors",
                state === "active" && "text-violet",
                (state === "done" || state === "skipped") && "text-text-secondary",
              )}
              style={final ? { color: final } : undefined}
            >
              {RIBBON_STAGE_LABELS[key]}
              {sub && <span className="mt-0.5 block text-[10px] font-normal normal-case tracking-normal text-text-tertiary">{sub}</span>}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
