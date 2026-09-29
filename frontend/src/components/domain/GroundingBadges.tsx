"use client";

import { ConfidenceRing } from "@/components/devices/ConfidenceRing";
import { getConfidenceSpec } from "@/lib/confidence";
import type { VerificationStatus } from "@/lib/types/ai";
import type { EvidenceConfidence } from "@/lib/types/reports";
import { cn } from "@/lib/utils";

/** Shared grounding vocabulary (Design System §9.1) — one implementation each, reused everywhere. */

export function VerificationBadge({ status, className }: { status: VerificationStatus; className?: string }) {
  const spec = getConfidenceSpec(status);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-pill border px-2.5 py-1 font-mono text-[10.5px]",
        className,
      )}
      style={{ borderColor: `color-mix(in oklch, var(${spec.colorVar}) 40%, transparent)`, color: `var(${spec.colorVar})` }}
    >
      <ConfidenceRing value={status} size={13} />
      {spec.label.toUpperCase()}
    </span>
  );
}

export function EvidenceConfidenceTag({ value, className }: { value: EvidenceConfidence; className?: string }) {
  const spec = getConfidenceSpec(value);
  return (
    <span
      className={cn("inline-flex items-center gap-1 rounded-pill px-2.5 py-1 font-mono text-[9.5px]", className)}
      style={{
        background: `color-mix(in oklch, var(${spec.colorVar}) 14%, transparent)`,
        color: `var(${spec.colorVar})`,
      }}
    >
      {spec.label.toUpperCase()}
    </span>
  );
}

export function CitationChip({
  fileRef,
  primary = false,
  onClick,
  className,
}: {
  fileRef: string;
  primary?: boolean;
  onClick?: () => void;
  className?: string;
}) {
  const Comp = onClick ? "button" : "span";
  return (
    <Comp
      onClick={onClick}
      className={cn(
        "inline-flex items-center rounded-pill px-2.5 py-1 font-mono text-[11px]",
        primary ? "bg-violet/[0.12] text-[oklch(0.82_0.11_300)]" : "text-text-secondary hover:text-text-primary",
        onClick && "cursor-pointer focus-visible:outline-2",
        className,
      )}
    >
      {fileRef}
    </Comp>
  );
}
