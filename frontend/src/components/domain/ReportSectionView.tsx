"use client";

import { EvidenceConfidenceTag } from "@/components/domain/GroundingBadges";
import type { ReportSection } from "@/lib/types/reports";

/**
 * Report section (Design System §16): boxless, rule-separated. The
 * primary narrative finding sits behind a violet-tinted left rule —
 * the same device Ask uses for CodeSage's own synthesized prose — so
 * "this is CodeSage's voice, here's its confidence tag" reads
 * consistently in the two places the product writes prose.
 */
export function ReportSectionView({ section, id }: { section: ReportSection; id?: string }) {
  return (
    <section id={id} className="border-t border-border-subtle pt-5 first:border-t-0 first:pt-0">
      <div className="flex items-baseline justify-between">
        <h3 className="font-sans text-h2 font-semibold text-text-primary">{section.heading}</h3>
        <EvidenceConfidenceTag value={section.confidence} />
      </div>

      <div className="mt-3 border-l-[1.5px] border-violet/30 pl-4">
        <p className="font-display text-[14.5px] italic leading-[1.75] text-text-primary/90">{section.content}</p>
      </div>

      {section.findings.length > 0 && (
        <ul className="mt-3 flex flex-col gap-1 pl-4 text-small text-text-secondary">
          {section.findings.map((finding, i) => (
            <li key={i}>&middot; {finding}</li>
          ))}
        </ul>
      )}

      {section.evidence.length > 0 && (
        <div className="mt-2.5 flex flex-wrap gap-[18px] font-mono text-[10.5px] text-text-tertiary">
          {section.evidence.map((ev, i) => (
            <span key={i}>
              {ev.file_path ?? ev.source}
              {ev.start_line && ev.end_line ? `:${ev.start_line}–${ev.end_line}` : ""}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}
