import type { StageLatency } from "@/lib/types/ai";

/**
 * Reasoning Ribbon stage reconciliation (Design System §17 trade-offs,
 * explicitly requiring this decision be made and documented before
 * implementation — not invented silently).
 *
 * The AI Engine's real LangGraph pipeline (backend/app/ai/engine/orchestrator.py)
 * runs seven stages, exposed on the wire as `AskMetadata.stage_latency_ms`
 * (backend/app/ai/schemas/dto.py::StageLatency):
 *
 *   intent -> retrieval -> evidence_selection -> context_construction
 *   -> llm -> verification -> formatting
 *
 * The Reasoning Ribbon is a 4-dot reader-facing device (Retrieve / Evidence
 * / Reason / Verify), per the approved canvas markup (Ask.dc.html). Decision
 * (per the design doc's own recommendation): keep 4 user-facing stages,
 * collapsing the 7 real stages as follows —
 *
 *   RETRIEVE  <- retrieval_ms
 *   EVIDENCE  <- evidence_selection_ms + context_construction_ms
 *   REASON    <- llm_ms
 *   VERIFY    <- verification_ms
 *
 * intent_ms and formatting_ms are real pipeline overhead but are NOT
 * shown as their own ribbon stage — they are folded into the total/"how
 * this was answered" disclosure instead, never silently dropped from the
 * data, only from the 4-dot visual. This mapping is intentionally a
 * constant, not a per-page decision, so it can't drift between Overview's
 * preview ribbon and the full Ask page's ribbon.
 */
export type RibbonStageKey = "retrieve" | "evidence" | "reason" | "verify";

export const RIBBON_STAGE_LABELS: Record<RibbonStageKey, string> = {
  retrieve: "Retrieve",
  evidence: "Evidence",
  reason: "Reason",
  verify: "Verify",
};

export const RIBBON_STAGE_ORDER: RibbonStageKey[] = ["retrieve", "evidence", "reason", "verify"];

export function mapStageLatencyToRibbon(stage: StageLatency): Record<RibbonStageKey, number> {
  return {
    retrieve: stage.retrieval_ms,
    evidence: stage.evidence_selection_ms + stage.context_construction_ms,
    reason: stage.llm_ms,
    verify: stage.verification_ms,
  };
}

/** Overhead intentionally not shown on the ribbon itself (documented above). */
export function ribbonOverheadMs(stage: StageLatency): number {
  return stage.intent_ms + stage.formatting_ms;
}
