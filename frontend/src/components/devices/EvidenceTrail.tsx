"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Signature device #3 — Evidence Trail (Design System §17-C).
 *
 * A thin dotted leader line with a small dot at each end, tethering a
 * claim in CodeSage's prose to its citation — a footnote thread made
 * visible. Ported from the approved canvas (`Ask.dc.html`'s `.cs-trail`
 * rule: `border-left:1px dotted oklch(1 0 0 / 0.18)`, a 4px dot above it).
 *
 * Responsive degradation (required — this must work responsively):
 * on narrow viewports (`compact`), the vertical leader line is dropped
 * entirely and only the small marker dot remains inline before the
 * citation text — there usually isn't enough vertical rhythm on mobile to
 * make a multi-line leader line read as a connector rather than clutter.
 */
interface EvidenceTrailProps {
  children: ReactNode;
  /** True for the highest-confidence/first citation (rendered slightly brighter). */
  primary?: boolean;
  /** Drop the leader line for narrow viewports — dot-only degradation. */
  compact?: boolean;
  className?: string;
}

export function EvidenceTrail({ children, primary = false, compact = false, className }: EvidenceTrailProps) {
  return (
    <div className={cn("flex items-start gap-2.5", className)}>
      <div className="flex flex-shrink-0 flex-col items-center pt-1.5">
        <span
          className={cn("h-1 w-1 rounded-full", primary ? "bg-violet" : "bg-text-tertiary")}
          aria-hidden="true"
        />
        {!compact && (
          <span
            className="mt-0.5 ml-px min-h-[10px] flex-1 border-l border-dotted border-white/20"
            aria-hidden="true"
          />
        )}
      </div>
      <div className="min-w-0 flex-1 font-mono text-[10.5px] leading-relaxed">{children}</div>
    </div>
  );
}
