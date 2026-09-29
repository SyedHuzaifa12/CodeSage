import type { EvidenceConfidence } from "@/lib/types/reports";
import type { VerificationStatus } from "@/lib/types/ai";

/**
 * The single, centrally-defined confidence -> arc-percentage mapping table
 * for the Confidence Ring signature device (Design System §17/§2-B,
 * "Confidence Ring"). Every place a VerificationStatus or EvidenceConfidence
 * is shown (Ask's SUPPORTED badge, Reports' VERIFIED/DERIVED tags, Graph's
 * centrality-adjacent confidence) reads from this ONE table — this is what
 * fixes the desktop/responsive dasharray inconsistency found in the design
 * audit "by construction," per the implementation brief: there is only one
 * component now, so there cannot be two different values for the same
 * semantic state.
 *
 * Values follow the design doc's own §17 trade-offs example verbatim:
 * SUPPORTED/VERIFIED -> 92%, PARTIALLY_SUPPORTED/PARTIAL -> 55%,
 * INSUFFICIENT_EVIDENCE -> 15%, CONTRADICTED -> 20% (danger color).
 * DERIVED (computed from confirmed deterministic facts, not itself
 * independently re-verified) sits just under VERIFIED at 78%.
 */
export interface ConfidenceSpec {
  /** 0-100. Drives the ring's stroke-dasharray. */
  arcPercent: number;
  /** CSS variable name (without var()), e.g. "--cs-success". */
  colorVar: string;
  /** Human-readable label shown next to the ring — never color alone (§12). */
  label: string;
}

export type ConfidenceValue = VerificationStatus | EvidenceConfidence;

export const CONFIDENCE_TABLE: Record<ConfidenceValue, ConfidenceSpec> = {
  supported: { arcPercent: 92, colorVar: "--cs-success", label: "Supported" },
  partially_supported: { arcPercent: 55, colorVar: "--cs-warning", label: "Partially supported" },
  insufficient_evidence: { arcPercent: 15, colorVar: "--cs-text-tertiary", label: "Insufficient evidence" },
  contradicted: { arcPercent: 20, colorVar: "--cs-danger", label: "Contradicted" },
  verified: { arcPercent: 92, colorVar: "--cs-success", label: "Verified" },
  derived: { arcPercent: 78, colorVar: "--cs-accent-violet", label: "Derived" },
  partial: { arcPercent: 55, colorVar: "--cs-warning", label: "Partial" },
};

export function getConfidenceSpec(value: ConfidenceValue | string): ConfidenceSpec {
  return (CONFIDENCE_TABLE as Record<string, ConfidenceSpec>)[value] ?? CONFIDENCE_TABLE.insufficient_evidence;
}

/**
 * Ring geometry: r=6 circle (matches the approved canvas markup exactly —
 * Ask.dc.html / Graph.dc.html / Components.dc.html all use viewBox 0 0 16 16,
 * cx=8 cy=8 r=6). Circumference ~= 37.7. The approved baseline used
 * stroke-dasharray="34 3.7" for the high-confidence state, i.e. ~90.2% —
 * we compute the dasharray from the percentage table above instead of
 * hardcoding per-instance strings, which is what actually prevents drift.
 */
export const CONFIDENCE_RING_RADIUS = 6;
export const CONFIDENCE_RING_CIRCUMFERENCE = 2 * Math.PI * CONFIDENCE_RING_RADIUS;

export function arcDasharray(arcPercent: number): string {
  const dash = (arcPercent / 100) * CONFIDENCE_RING_CIRCUMFERENCE;
  const gap = CONFIDENCE_RING_CIRCUMFERENCE - dash;
  return `${dash.toFixed(1)} ${gap.toFixed(1)}`;
}
