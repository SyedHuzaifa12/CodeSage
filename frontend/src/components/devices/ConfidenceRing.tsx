"use client";

import { CONFIDENCE_RING_RADIUS, arcDasharray, getConfidenceSpec, type ConfidenceValue } from "@/lib/confidence";
import { cn } from "@/lib/utils";

/**
 * Signature device #2 — Confidence Ring (Design System §17-B).
 *
 * A partial-arc ring whose arc length encodes a VerificationStatus or
 * EvidenceConfidence value, replacing the flat colored dot used
 * everywhere before. Geometry ported verbatim from the approved canvas
 * (Ask.dc.html/Graph.dc.html/Components.dc.html): viewBox 0 0 16 16,
 * cx=8 cy=8 r=6, stroke-linecap round, rotated -90deg so the arc starts
 * at 12 o'clock. The arc percentage always comes from the single
 * lib/confidence.ts table — never hardcoded per instance, which is what
 * fixes the desktop/responsive dasharray mismatch by construction.
 */
interface ConfidenceRingProps {
  value: ConfidenceValue | string;
  size?: number;
  /** Show the mono text label beside the ring (icon+label, never color alone — §12). */
  withLabel?: boolean;
  className?: string;
}

export function ConfidenceRing({ value, size = 15, withLabel = false, className }: ConfidenceRingProps) {
  const spec = getConfidenceSpec(value);
  const color = `var(${spec.colorVar})`;
  const dasharray = arcDasharray(spec.arcPercent);

  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      <svg width={size} height={size} viewBox="0 0 16 16" role="img" aria-label={`Confidence: ${spec.label}`}>
        <circle
          cx={8}
          cy={8}
          r={CONFIDENCE_RING_RADIUS}
          fill="none"
          stroke={color}
          strokeOpacity={0.18}
          strokeWidth={2.2}
        />
        <circle
          cx={8}
          cy={8}
          r={CONFIDENCE_RING_RADIUS}
          fill="none"
          stroke={color}
          strokeWidth={2.2}
          strokeDasharray={dasharray}
          strokeLinecap="round"
          transform="rotate(-90 8 8)"
        />
      </svg>
      {withLabel && (
        <span className="font-mono text-[10.5px] uppercase tracking-wide" style={{ color }}>
          {spec.label}
        </span>
      )}
    </span>
  );
}
