"use client";

import { RIBBON_STAGE_LABELS, RIBBON_STAGE_ORDER, type RibbonStageKey } from "@/lib/reasoningRibbon";
import { getConfidenceSpec } from "@/lib/confidence";
import type { VerificationStatus } from "@/lib/types/ai";
import { cn } from "@/lib/utils";

/**
 * Signature device #4 — Reasoning Ribbon (Design System §17-D).
 *
 * A slim vertical sequence of four dots (Retrieve · Evidence · Reason ·
 * Verify), connected by a thin line, filled in as each stage completes.
 * This is literally Sprint 5's LangGraph pipeline stages (see
 * lib/reasoningRibbon.ts for the exact stage-collapse mapping) made
 * visible as product identity. Ported from the approved canvas
 * (`Ask.dc.html`'s `.cs-ribbon-dot`/`.cs-ribbon-line` rules, both the
 * "complete" and "mid-pipeline thinking" states).
 *
 * Built against a streaming-shaped interface (Design System §13): the Ask
 * page drives `stageStates` from the same AnswerStream callbacks used for
 * the token reveal, so a future real-streaming backend updates this
 * component with zero API changes.
 */
export type StageState = "pending" | "active" | "done";

interface ReasoningRibbonProps {
  /** One state per RIBBON_STAGE_ORDER entry: [retrieve, evidence, reason, verify]. */
  stageStates: Record<RibbonStageKey, StageState>;
  /** Colors the final ("verify") dot once done, using the shared confidence table. */
  finalStatus?: VerificationStatus;
  size?: "sm" | "md";
  className?: string;
}

export function ReasoningRibbon({ stageStates, finalStatus, size = "md", className }: ReasoningRibbonProps) {
  const dotSize = size === "sm" ? 5 : 6;
  const lineHeight = size === "sm" ? 7 : 9;

  return (
    <div
      className={cn("flex flex-shrink-0 flex-col items-center pt-1", className)}
      role="img"
      aria-label={reasoningRibbonSummary(stageStates, finalStatus)}
    >
      {RIBBON_STAGE_ORDER.map((key, i) => {
        const state = stageStates[key];
        const isLast = i === RIBBON_STAGE_ORDER.length - 1;
        const doneColor =
          isLast && state === "done" && finalStatus
            ? `var(${getConfidenceSpec(finalStatus).colorVar})`
            : "var(--cs-accent-violet)";

        return (
          <div key={key} className="flex flex-col items-center">
            <span
              className="rounded-full flex-shrink-0"
              style={{
                width: dotSize,
                height: dotSize,
                background: state === "done" || state === "active" ? doneColor : "transparent",
                border: state === "pending" ? "1px solid var(--cs-text-tertiary)" : undefined,
                boxShadow: state === "active" ? `0 0 0 3px color-mix(in oklch, ${doneColor} 18%, transparent)` : undefined,
              }}
              aria-hidden="true"
            />
            {!isLast && (
              <span
                className="w-px flex-shrink-0"
                style={{
                  height: lineHeight,
                  background:
                    state === "done"
                      ? "color-mix(in oklch, var(--cs-accent-violet) 35%, transparent)"
                      : "oklch(1 0 0 / 0.08)",
                }}
                aria-hidden="true"
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

/** The horizontal mono label strip used beside/above the ribbon (RETRIEVE · EVIDENCE · REASON · VERIFY). */
export function ReasoningRibbonLabels({
  stageStates,
  finalStatus,
  className,
}: {
  stageStates: Record<RibbonStageKey, StageState>;
  finalStatus?: VerificationStatus;
  className?: string;
}) {
  return (
    <div className={cn("font-mono text-[9px] uppercase tracking-wider text-text-tertiary", className)}>
      {RIBBON_STAGE_ORDER.map((key, i) => {
        const state = stageStates[key];
        const isLast = i === RIBBON_STAGE_ORDER.length - 1;
        const label =
          isLast && state === "done" && finalStatus
            ? getConfidenceSpec(finalStatus).label.toUpperCase()
            : RIBBON_STAGE_LABELS[key].toUpperCase();
        const color =
          state === "active"
            ? "var(--cs-accent-violet)"
            : state === "done"
              ? isLast && finalStatus
                ? `var(${getConfidenceSpec(finalStatus).colorVar})`
                : "var(--cs-text-secondary)"
              : undefined;
        return (
          <span key={key} style={color ? { color } : undefined}>
            {i > 0 && <span className="mx-1 text-text-tertiary">&middot;</span>}
            {label}
          </span>
        );
      })}
    </div>
  );
}

function reasoningRibbonSummary(
  stageStates: Record<RibbonStageKey, StageState>,
  finalStatus?: VerificationStatus,
): string {
  const done = RIBBON_STAGE_ORDER.filter((k) => stageStates[k] === "done").length;
  const suffix = finalStatus ? `, verification: ${getConfidenceSpec(finalStatus).label}` : "";
  return `Reasoning pipeline: ${done} of ${RIBBON_STAGE_ORDER.length} stages complete${suffix}`;
}
