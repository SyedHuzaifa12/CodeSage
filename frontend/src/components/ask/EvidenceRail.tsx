"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { ConfidenceRing } from "@/components/devices/ConfidenceRing";
import type { AskTurn } from "@/lib/askSession";
import type { Citation } from "@/lib/types/ai";
import type { SymbolExplorerItem } from "@/lib/types/workspace";
import { cn } from "@/lib/utils";

export const STAGE_DESCRIPTIONS = [
  "Retrieving — semantic ∥ lexical, then one-hop structural expansion",
  "Selecting evidence — at most 8 items, 2 per file; reading the cited lines",
  "Reasoning — one LLM call, constrained to the evidence",
  "Verifying — every file, symbol() and line range against the evidence",
];

export const loc = (c: Pick<Citation, "file_path" | "start_line" | "end_line">) =>
  `${c.file_path}${c.start_line ? `:${c.start_line}${c.end_line && c.end_line !== c.start_line ? `–${c.end_line}` : ""}` : ""}`;

export function SourcePill({ source }: { source: string }) {
  return <span className={cn("cs-pill", `cs-pill-${source}`)}>{source}</span>;
}

/** candidates → evidence items → files: how much of the repository the answer actually drew on. */
function ContextAperture({ candidates, items, files }: { candidates: number; items: number; files: number }) {
  const max = Math.max(1, candidates);
  const W = (v: number) => Math.max(v ? 14 : 4, (v / max) * 116);
  const widths = [W(candidates), W(items), W(files)];
  const ys = [6, 52, 98];
  const H = 32;
  const cx = 60;
  const labels: [number, string][] = [
    [candidates, "retrieval candidates"],
    [items, "evidence items"],
    [files, "files in context"],
  ];
  const fills = ["oklch(1 0 0 / .08)", "oklch(0.75 0.13 300 / .24)", "oklch(0.75 0.13 300 / .6)"];
  return (
    <svg viewBox="0 0 260 136" className="mb-1.5 mt-3 block h-auto w-full" role="img" aria-label={`${candidates} retrieval candidates narrowed to ${items} evidence items from ${files} files`}>
      {widths.map((w, i) => {
        const w2 = i < 2 ? widths[i + 1] : w * 0.8;
        const y = ys[i];
        return (
          <g key={i}>
            <path
              d={`M${cx - w / 2} ${y} L${cx + w / 2} ${y} L${cx + w2 / 2} ${y + H} L${cx - w2 / 2} ${y + H} Z`}
              fill={fills[i]}
              stroke={i === 2 ? "var(--cs-accent-violet)" : "oklch(1 0 0 / .14)"}
              style={{ transformBox: "fill-box", transformOrigin: "center top", animation: `cs-fade-in 600ms var(--cs-ease-out) ${i * 120}ms both` }}
            />
            <line x1={cx + w / 2 + 6} y1={y + H / 2} x2={128} y2={y + H / 2} stroke="oklch(1 0 0 / .12)" strokeDasharray="1.5 3" />
            <text x={136} y={y + 14} fontFamily="var(--font-plex-mono)" fontSize={15} fontWeight={500} fill={i === 2 ? "var(--cs-accent-violet)" : "var(--cs-text-primary)"}>
              {labels[i][0]}
            </text>
            <text x={136} y={y + 28} fontFamily="var(--font-plex-mono)" fontSize={9.5} fill="var(--cs-text-tertiary)">
              {labels[i][1]}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function EvidenceItem({
  c,
  index,
  primary,
  open,
  hovered,
  symbol,
  repositoryId,
  onToggle,
  onHover,
}: {
  c: Citation;
  index: number;
  primary?: boolean;
  open: boolean;
  hovered: boolean;
  symbol?: SymbolExplorerItem;
  repositoryId: string;
  onToggle: () => void;
  onHover: (i: number | null) => void;
}) {
  return (
    <div>
      <button
        type="button"
        data-ev={index}
        onClick={onToggle}
        onMouseEnter={() => onHover(index)}
        onMouseLeave={() => onHover(null)}
        aria-expanded={open}
        className={cn(
          "block w-full rounded-[8px] border border-transparent border-l-2 px-3 py-2.5 text-left transition-colors",
          (open || hovered) && "border-border-subtle border-l-violet bg-[linear-gradient(90deg,oklch(0.2_0.012_280),oklch(0.175_0.009_280))]",
        )}
      >
        <div className="break-all font-mono text-[11.5px] font-medium leading-snug text-text-primary">
          {!primary && <span className="mr-1.5 text-[9.5px] text-violet">{index + 1}</span>}
          {loc(c)}
        </div>
        {c.symbol_name && (
          <div className="mt-0.5 break-all font-mono text-[11.5px] text-violet">
            {c.symbol_type} {c.symbol_name}
          </div>
        )}
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 font-mono text-[10.5px] text-text-tertiary">
          score {c.retrieval_score.toFixed(2)} ·{c.retrieval_sources.map((s) => <SourcePill key={s} source={s} />)}
        </div>
        <div className="cs-bar mt-2 !h-[2px]">
          <i style={{ width: `${Math.min(100, c.retrieval_score * 100)}%` }} />
        </div>
      </button>
      {open && (
        <div className="cs-fade-in mb-2.5 ml-3.5 mt-0.5 border-t border-dashed border-border-strong pt-2.5">
          {symbol ? (
            <dl className="cs-kv">
              <dt>qualified</dt>
              <dd>{symbol.qualified_name}</dd>
              {symbol.signature && (
                <>
                  <dt>signature</dt>
                  <dd>{symbol.signature}</dd>
                </>
              )}
              <dt>visibility</dt>
              <dd>{symbol.visibility}</dd>
              <dt>lines</dt>
              <dd>
                {symbol.start_line}–{symbol.end_line}
              </dd>
            </dl>
          ) : (
            <p className="text-small text-text-tertiary">No parsed symbol for this range — the evidence is a file chunk.</p>
          )}
          <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1">
            <Link className="cs-link" href={`/r/${repositoryId}/explorer?file=${encodeURIComponent(c.file_path)}${c.start_line ? `&line=${c.start_line}` : ""}`}>
              open in Explorer <ArrowRight size={13} aria-hidden="true" />
            </Link>
            {c.symbol_name && (
              <Link className="cs-link cs-link-quiet" href={`/r/${repositoryId}/search?q=${encodeURIComponent(c.symbol_name)}`}>
                search
              </Link>
            )}
          </div>
          <p className="mt-2.5 text-[11.5px] text-text-tertiary">The API returns citation metadata only — no source text is shown.</p>
        </div>
      )}
    </div>
  );
}

/** Right-margin evidence column (Design System §16 Ask): everything the selected answer was grounded in. */
export function EvidenceRail({
  turn,
  repositoryId,
  symbols,
  openIndex,
  hovered,
  onToggle,
  onHover,
}: {
  turn: AskTurn | undefined;
  repositoryId: string;
  symbols?: SymbolExplorerItem[];
  openIndex: number | null;
  hovered: number | null;
  onToggle: (i: number) => void;
  onHover: (i: number | null) => void;
}) {
  if (!turn) {
    return (
      <div className="flex flex-col">
        <section>
          <p className="cs-mono-label">Evidence</p>
          <p className="mt-2 text-small text-text-secondary">
            When you ask, the evidence CodeSage retrieved appears here — every claim in an answer traces back to a file, symbol and line range.
          </p>
          <ol className="mt-3 grid list-none gap-2.5 p-0 font-mono text-[11.5px] text-text-tertiary">
            {STAGE_DESCRIPTIONS.map((s) => (
              <li key={s} className="grid grid-cols-[14px_1fr] gap-2">
                <i className="mt-[5px] h-[7px] w-[7px] rounded-full border-[1.5px] border-current" aria-hidden="true" />
                {s}
              </li>
            ))}
          </ol>
        </section>
        <section className="mt-5 border-t border-border-subtle pt-[18px]">
          <p className="cs-mono-label">Grounding rules</p>
          <p className="mt-2 text-small text-text-secondary">
            Answers come only from retrieved repository evidence. When the evidence isn&rsquo;t there, CodeSage says so instead of guessing.
          </p>
        </section>
      </div>
    );
  }
  if (turn.status === "thinking" || turn.status === "error" || !turn.response) {
    return (
      <section>
        <p className="cs-mono-label">{turn.status === "error" ? "Pipeline stopped" : "Working"}</p>
        <ol className="mt-3 grid list-none gap-2.5 p-0 font-mono text-[11.5px] text-text-tertiary" aria-live="polite">
          {STAGE_DESCRIPTIONS.map((s, i) => {
            const on = turn.status === "thinking" && i === turn.stage;
            const done = i < turn.stage;
            return (
              <li key={s} className={cn("grid grid-cols-[14px_1fr] gap-2 transition-colors", on && "text-violet", done && "text-text-secondary")}>
                <i className={cn("mt-[5px] h-[7px] w-[7px] rounded-full border-[1.5px] border-current", (on || done) && "bg-current", on && "cs-pulse")} aria-hidden="true" />
                {s}
              </li>
            );
          })}
        </ol>
        <p className="mt-4 text-small text-text-tertiary">Stage progress here is paced by the client; real per-stage timings arrive with the answer.</p>
      </section>
    );
  }
  const res = turn.response;
  const ev = res.evidence;
  const m = res.metadata;
  const sources = [...new Set(ev.flatMap((e) => e.retrieval_sources))];
  const symbolFor = (c: Citation) =>
    symbols?.find((s) => s.file_path === c.file_path && s.name === c.symbol_name && s.start_line === c.start_line) ??
    symbols?.find((s) => s.file_path === c.file_path && s.name === c.symbol_name);
  return (
    <div className="flex flex-col">
      <section>
        <p className="cs-mono-label">Context aperture</p>
        <ContextAperture candidates={m.retrieval_candidates} items={ev.length} files={res.relevant_files.length} />
        <p className="cs-monoline !text-[11px]">
          {res.relevant_files.length} files · {sources.length ? sources.join(" + ") : "no sources"}
        </p>
      </section>
      <section className="mt-5 border-t border-border-subtle pt-[18px]">
        <p className="cs-mono-label">Primary evidence</p>
        {ev[0] ? (
          <div className="mt-2">
            <EvidenceItem
              c={ev[0]}
              index={0}
              primary
              open={openIndex === 0}
              hovered={hovered === 0}
              symbol={symbolFor(ev[0])}
              repositoryId={repositoryId}
              onToggle={() => onToggle(0)}
              onHover={onHover}
            />
          </div>
        ) : (
          <p className="mt-2 text-small text-text-secondary">None — {res.verification.reasons[0] ?? "no evidence cleared the relevance floor."}</p>
        )}
      </section>
      {ev.length > 1 && (
        <section className="mt-5 border-t border-border-subtle pt-[18px]">
          <p className="cs-mono-label">All evidence · {ev.length}</p>
          <div className="mt-2">
            {ev.slice(1).map((c, j) => (
              <EvidenceItem
                key={`${c.file_path}-${c.start_line}-${j}`}
                c={c}
                index={j + 1}
                open={openIndex === j + 1}
                hovered={hovered === j + 1}
                symbol={symbolFor(c)}
                repositoryId={repositoryId}
                onToggle={() => onToggle(j + 1)}
                onHover={onHover}
              />
            ))}
          </div>
        </section>
      )}
      <section className="mt-5 border-t border-border-subtle pt-[18px]">
        <p className="cs-mono-label">How this was answered</p>
        <dl className="cs-kv mt-2">
          <dt>intent</dt>
          <dd>{m.intent}</dd>
          <dt>model</dt>
          <dd>{m.model || "— (declined before the LLM)"}</dd>
          <dt>total</dt>
          <dd>{m.cache_hit ? `${m.stage_latency_ms.total_ms}ms · cache hit` : `${m.stage_latency_ms.total_ms.toLocaleString("en-US")}ms`}</dd>
          <dt>verdict</dt>
          <dd>
            <ConfidenceRing value={res.verification.status} withLabel />
          </dd>
        </dl>
      </section>
    </div>
  );
}
