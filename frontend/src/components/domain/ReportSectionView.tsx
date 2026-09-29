"use client";

import { ConfidenceRing } from "@/components/devices/ConfidenceRing";
import { Notice } from "@/components/state/StateVocabulary";
import { classifyRisk } from "@/lib/graphModel";
import { splitUngrounded } from "@/lib/reportFormat";
import type { EvidenceReference, ReportSection } from "@/lib/types/reports";
import { cn } from "@/lib/utils";

const PALETTE = ["var(--cs-accent-violet)", "var(--cs-accent-cyan)", "var(--cs-warning)", "var(--cs-success)", "var(--cs-info)", "var(--cs-text-tertiary)"];
const RISK_COLOR = { high: "var(--cs-danger)", medium: "var(--cs-warning)", low: "var(--cs-text-tertiary)" } as const;

function evidenceLine(e: EvidenceReference): string {
  const where = e.file_path ? `${e.file_path}${e.start_line ? `:${e.start_line}${e.end_line && e.end_line !== e.start_line ? `–${e.end_line}` : ""}` : ""}` : null;
  return [where, e.symbol_name, e.relationship_type, e.description, !where && !e.description ? e.source : null].filter(Boolean).join(" · ");
}

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

function Metrics({ metrics, cycles }: { metrics: Record<string, unknown>; cycles: string[][] }) {
  const scalars: [string, string][] = [];
  const blocks: JSX.Element[] = [];
  for (const [key, value] of Object.entries(metrics)) {
    if (Array.isArray(value) && value.every((v) => isRecord(v) && "module_path" in v && "incoming_dependencies" in v)) {
      const rows = value as { module_path: string; incoming_dependencies: number; risk?: "high" | "medium" | "low" }[];
      const max = Math.max(1, ...rows.map((r) => r.incoming_dependencies));
      blocks.push(
        <div key={key} className="mt-4" role="table" aria-label="Dependency hotspots">
          {rows.map((r) => {
            const risk = r.risk ?? classifyRisk(r.module_path, r.incoming_dependencies, cycles);
            return (
              <div key={r.module_path} role="row" className="grid grid-cols-[minmax(0,1fr)_54px_26px_56px] items-center gap-2 border-t border-border-subtle py-[9px] font-mono text-[12px] sm:grid-cols-[minmax(0,190px)_minmax(0,1fr)_34px_70px] sm:gap-3.5">
                <span role="cell" className="truncate text-text-primary">{r.module_path}</span>
                <span role="cell" className="h-[7px] overflow-hidden rounded bg-surface-3">
                  <i className="block h-full rounded" style={{ width: `${(r.incoming_dependencies / max) * 100}%`, background: RISK_COLOR[risk], transformOrigin: "left", animation: "cs-grow 700ms var(--cs-ease-out) both" }} />
                </span>
                <span role="cell" className="cs-tabular text-right text-text-secondary">{r.incoming_dependencies}</span>
                <span role="cell" className="text-[10.5px] uppercase tracking-[0.08em]" style={{ color: RISK_COLOR[risk] }}>
                  {risk}
                </span>
              </div>
            );
          })}
        </div>,
      );
    } else if (Array.isArray(value) && value.every((v) => isRecord(v) && "path" in v && "symbol_count" in v)) {
      const rows = value as { path: string; symbol_count: number }[];
      const max = Math.max(1, ...rows.map((r) => r.symbol_count));
      blocks.push(
        <div key={key} className="mt-4">
          {rows.slice(0, 10).map((r) => (
            <div key={r.path} className="grid grid-cols-[minmax(0,1fr)_34px] items-center gap-x-2.5 gap-y-1 border-t border-border-subtle py-2 font-mono text-[12px] text-text-secondary">
              <span className="truncate">{r.path}</span>
              <b className="text-right font-medium text-text-primary">{r.symbol_count}</b>
              <span className="cs-bar col-span-2 !h-[2px]">
                <i style={{ width: `${(r.symbol_count / max) * 100}%` }} />
              </span>
            </div>
          ))}
        </div>,
      );
    } else if (isRecord(value) && Object.values(value).every((v) => typeof v === "number")) {
      const entries = Object.entries(value as Record<string, number>).sort((a, b) => b[1] - a[1]);
      if (!entries.length) continue;
      blocks.push(
        <div key={key} className="mt-4">
          <div className="flex h-2 gap-0.5 overflow-hidden rounded" aria-hidden="true">
            {entries.map(([k, n], i) => (
              <i key={k} className="h-full" style={{ flex: n, background: PALETTE[i % PALETTE.length] }} />
            ))}
          </div>
          <div className="mt-2.5 flex flex-wrap gap-x-5 gap-y-1 font-mono text-[11.5px] text-text-tertiary">
            {entries.map(([k, n], i) => (
              <span key={k}>
                <span style={{ color: PALETTE[i % PALETTE.length] }} aria-hidden="true">
                  ●
                </span>{" "}
                {k} <b className="font-medium text-text-primary">{n}</b>
              </span>
            ))}
          </div>
        </div>,
      );
    } else if (typeof value === "number" || typeof value === "string") {
      const label = key.replace(/_/g, " ");
      const display =
        typeof value === "number"
          ? key.includes("bytes")
            ? value >= 1e6
              ? `${(value / 1e6).toFixed(1)} MB`
              : `${(value / 1e3).toFixed(1)} KB`
            : key.includes("ratio")
              ? `${Math.round(value * 100)}%`
              : value.toLocaleString("en-US")
          : value;
      scalars.push([label, display]);
    }
  }
  return (
    <>
      {scalars.length > 0 && (
        <div className="mt-3.5 flex flex-wrap gap-x-5 gap-y-1.5 font-mono text-[11.5px] text-text-tertiary">
          {scalars.map(([k, v]) => (
            <span key={k}>
              {k} <b className="cs-tabular font-medium text-text-primary">{v}</b>
            </span>
          ))}
        </div>
      )}
      {blocks}
    </>
  );
}

/**
 * One report section (Design System §9.4/§16). Provenance is explicit:
 * deterministic sections read as plain facts; the single AI-written
 * section sits behind CodeSage's violet voice rule with an AI tag.
 */
export function ReportSectionView({
  section,
  id,
  index,
  ai,
  cycles = [],
  children,
}: {
  section: ReportSection;
  id?: string;
  index: number;
  ai: boolean;
  cycles?: string[][];
  children?: React.ReactNode;
}) {
  const { ungrounded, text } = splitUngrounded(section.content);
  return (
    <section id={id} aria-labelledby={`${id}-h`} className="scroll-mt-20 border-t border-border-subtle pb-[26px] pt-[30px]" style={{ animation: `cs-rise 520ms var(--cs-ease-out) ${Math.min(index, 6) * 50}ms both` }}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
        <h2 id={`${id}-h`} className="flex items-baseline gap-2 font-sans text-[18px] font-semibold tracking-[-0.006em] text-text-primary">
          <span className="min-w-[26px] font-mono text-[10.5px] font-medium tracking-[0.04em] text-violet">{String(index + 1).padStart(2, "0")}</span>
          {section.heading}
          {ai && (
            <span className="cs-tag text-violet" title="Written by a single LLM call over the deterministic facts, then citation-checked">
              AI
            </span>
          )}
        </h2>
        <ConfidenceRing value={section.confidence} withLabel />
      </div>
      {ungrounded && (
        <Notice tone="warn" className="mt-3" title="Could not be fully grounded">
          This AI interpretation could not be verified against repository evidence — treat it as unverified.
        </Notice>
      )}
      {ai ? (
        <div className="cs-voice mt-3 rounded-r-[10px] bg-[linear-gradient(90deg,oklch(0.75_0.13_300/0.065),transparent_75%)] py-4 pr-5">
          <p className="font-display text-[17.5px] italic leading-[1.7] text-text-primary">{text}</p>
        </div>
      ) : (
        <p className={cn("mt-3 max-w-[66ch] break-words text-[14px] leading-[1.75] text-[oklch(0.76_0.01_280)]")}>{text}</p>
      )}
      {section.findings.length > 0 && (
        <ul className="m-0 mt-3.5 list-none p-0">
          {section.findings.map((f) => (
            <li key={f} className="relative break-words border-t border-border-subtle py-2 pl-[18px] text-[13.5px] before:absolute before:left-0.5 before:top-[17px] before:h-[1.5px] before:w-[7px] before:bg-violet">
              {f}
            </li>
          ))}
        </ul>
      )}
      {Object.keys(section.metrics).length > 0 && <Metrics metrics={section.metrics} cycles={cycles} />}
      {children}
      {section.evidence.length > 0 && (
        <ol className="m-0 mt-[18px] list-none border-t border-dashed border-border-subtle p-0 pt-2.5 font-mono text-[11px] leading-relaxed text-text-tertiary" aria-label="Evidence">
          {section.evidence.map((e, i) => (
            <li key={i} className="grid grid-cols-[22px_1fr] break-words">
              <span className="text-violet">{i + 1}</span>
              <span>{evidenceLine(e)}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
