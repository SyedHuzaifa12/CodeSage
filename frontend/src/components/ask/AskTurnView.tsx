"use client";

import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Copy, FileCode2, Info, RefreshCw } from "lucide-react";
import { AnswerProse } from "@/components/ask/AnswerProse";
import { loc } from "@/components/ask/EvidenceRail";
import { ThinkingSteps } from "@/components/ask/ThinkingSteps";
import { TopologyMark } from "@/components/devices/TopologyMark";
import { VerificationBadge } from "@/components/domain/GroundingBadges";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/state/StateVocabulary";
import { plainText } from "@/lib/answerFormat";
import { ApiError } from "@/lib/api/client";
import type { AskTurn } from "@/lib/askSession";
import { ribbonOverheadMs } from "@/lib/reasoningRibbon";
import type { AskResponseData, Citation } from "@/lib/types/ai";
import { cn } from "@/lib/utils";

const SEGMENTS: { key: string; label: string; color: string; ms: (r: AskResponseData) => number }[] = [
  { key: "intent", label: "intent", color: "var(--cs-text-tertiary)", ms: (r) => r.metadata.stage_latency_ms.intent_ms },
  { key: "retrieval", label: "retrieval", color: "var(--cs-accent-cyan)", ms: (r) => r.metadata.stage_latency_ms.retrieval_ms },
  { key: "evidence", label: "evidence", color: "var(--cs-info)", ms: (r) => r.metadata.stage_latency_ms.evidence_selection_ms + r.metadata.stage_latency_ms.context_construction_ms },
  { key: "reasoning", label: "reasoning", color: "var(--cs-accent-violet)", ms: (r) => r.metadata.stage_latency_ms.llm_ms },
  { key: "verification", label: "verification", color: "var(--cs-success)", ms: (r) => r.metadata.stage_latency_ms.verification_ms },
  { key: "formatting", label: "formatting", color: "var(--cs-text-tertiary)", ms: (r) => r.metadata.stage_latency_ms.formatting_ms },
];

function Disclosure({ res }: { res: AskResponseData }) {
  const m = res.metadata;
  const L = m.stage_latency_ms;
  const total = SEGMENTS.reduce((a, s) => a + s.ms(res), 0) || 1;
  return (
    <div className="cs-panel cs-fade-in mt-3 px-[18px] py-4">
      <dl className="cs-kv">
        <dt>intent</dt>
        <dd>{m.intent}</dd>
        <dt>provider</dt>
        <dd>{m.provider ? `${m.provider} / ${m.model}` : "— (declined before the LLM)"}</dd>
        <dt>cache</dt>
        <dd>{m.cache_hit ? `hit (${L.total_ms}ms)` : `miss (${L.total_ms.toLocaleString("en-US")}ms)`}</dd>
        {!m.cache_hit && (
          <>
            <dt>retries</dt>
            <dd>{m.retry_count}</dd>
            <dt>candidates</dt>
            <dd>{m.retrieval_candidates}</dd>
            <dt>tokens</dt>
            <dd>{m.prompt_tokens != null ? `${m.prompt_tokens.toLocaleString("en-US")} prompt · ${(m.completion_tokens ?? 0).toLocaleString("en-US")} completion` : "—"}</dd>
            <dt>overhead</dt>
            <dd>{ribbonOverheadMs(L)}ms intent + formatting</dd>
          </>
        )}
      </dl>
      {m.cache_hit ? (
        // On a cache hit the backend's per-stage breakdown belongs to the original generation, not this fast response.
        <p className="mt-3 text-small text-text-tertiary">Answered from the 30-minute answer cache. Per-stage timings are hidden because they belong to the original run.</p>
      ) : (
        <>
          <div className="cs-latbar mt-3.5" aria-hidden="true">
            {SEGMENTS.map((s) => (
              <i key={s.key} style={{ flex: Math.max(s.ms(res), total * 0.004), background: s.color }} title={`${s.label} ${s.ms(res)}ms`} />
            ))}
          </div>
          <div className="mt-2 flex flex-wrap gap-x-3.5 gap-y-1 font-mono text-[10.5px] text-text-tertiary">
            {SEGMENTS.map((s) => (
              <span key={s.key}>
                <i className="cs-legend-dot" style={{ background: s.color }} aria-hidden="true" />
                {s.label} {s.ms(res)}ms
              </span>
            ))}
          </div>
        </>
      )}
      <p className="mt-4 text-small font-medium text-text-tertiary">Verification</p>
      <ul className="cs-reasons mt-2">
        {res.verification.reasons.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
      <p className="mt-3 text-small text-text-tertiary">
        Verification is deterministic — no second model call. It checks cited file paths, <span className="font-mono">symbol()</span> names and line
        ranges against the evidence the model was given; prose without a citable artifact isn&rsquo;t checked.
      </p>
    </div>
  );
}

/** Copies text, falling back to a hidden textarea where the async clipboard API is unavailable (older browsers, http). */
async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.cssText = "position:fixed;opacity:0;pointer-events:none";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      ta.remove();
      return ok;
    } catch {
      return false;
    }
  }
}

const actionClass =
  "inline-flex h-8 items-center gap-1.5 rounded-[8px] px-2.5 text-[12.5px] font-medium text-text-tertiary transition-colors hover:bg-surface-2 hover:text-text-primary focus-visible:outline-2";

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => () => clearTimeout(timer.current), []);
  return (
    <button
      type="button"
      className={actionClass}
      onClick={async () => {
        if (await copyText(text)) {
          setCopied(true);
          clearTimeout(timer.current);
          timer.current = setTimeout(() => setCopied(false), 1800);
        }
      }}
    >
      {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
      <span aria-live="polite">{copied ? "Copied" : "Copy"}</span>
    </button>
  );
}

const VISIBLE_SOURCES = 4;

function SourceChip({
  c,
  index,
  active,
  onCite,
  onHover,
}: {
  c: Citation;
  index: number;
  active: boolean;
  onCite: (i: number) => void;
  onHover: (i: number | null) => void;
}) {
  // Two path segments, not one: a project often has several files with the same name (__init__.py, index.ts).
  const name = c.file_path.split("/").slice(-2).join("/");
  const lines = c.start_line ? `:${c.start_line}${c.end_line && c.end_line !== c.start_line ? `–${c.end_line}` : ""}` : "";
  return (
    <button
      type="button"
      title={loc(c)}
      onClick={() => onCite(index)}
      onMouseEnter={() => onHover(index)}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover(index)}
      onBlur={() => onHover(null)}
      aria-label={`Source ${index + 1}: ${loc(c)}${index === 0 ? " (primary)" : ""}`}
      className={cn(
        "inline-flex max-w-full items-center gap-2 rounded-[8px] border bg-surface-1 px-2.5 py-1.5 text-left text-[12.5px] shadow-sm transition-colors hover:bg-surface-2",
        active || index === 0 ? "border-[var(--cs-violet-line)]" : "border-border-strong",
      )}
    >
      <FileCode2 size={14} strokeWidth={1.7} className={cn("flex-none", index === 0 ? "text-violet" : "text-text-tertiary")} aria-hidden="true" />
      <span className="truncate font-medium text-text-primary">{name}</span>
      {lines && <span className="flex-none font-mono text-[11.5px] text-text-tertiary">{lines}</span>}
      {index === 0 && <span className="flex-none rounded bg-[var(--cs-violet-tint)] px-1.5 py-px text-[10.5px] font-semibold text-violet">Primary</span>}
    </button>
  );
}

/**
 * One exchange in the conversation: the user's question as a bubble on the right, CodeSage's answer on the left with
 * its sources, verification, and actions beneath. While it works it shows the stages it is going through.
 */
export function AskTurnView({
  turn,
  hovered,
  onHover,
  onCite,
  onRetry,
  onCancel,
  onFollowUp,
}: {
  turn: AskTurn;
  hovered: number | null;
  onHover: (i: number | null) => void;
  onCite: (i: number) => void;
  onRetry: () => void;
  onCancel: () => void;
  onFollowUp: (q: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const res = turn.response;
  const status = res?.verification.status;
  const muted = status === "contradicted";
  const ev = res?.evidence ?? [];
  const hint =
    status === "insufficient_evidence"
      ? "Try naming a specific file, symbol or module."
      : status === "contradicted"
        ? "Try asking about a more specific file, symbol or module."
        : null;
  const followUps =
    status === "supported" || status === "partially_supported"
      ? (res?.relevant_files ?? []).slice(0, 3).map((f) => `Explain ${f}`).filter((q) => q.toLowerCase() !== turn.question.toLowerCase())
      : [];
  const err = turn.error;
  const sources = showAll ? ev : ev.slice(0, VISIBLE_SOURCES);

  return (
    <article className="mt-8 scroll-mt-5 first:mt-2" aria-label={`Question: ${turn.question}`}>
      <div className="flex justify-end">
        <p className="max-w-[88%] whitespace-pre-wrap break-words rounded-[18px] rounded-br-[6px] border border-border-subtle bg-surface-3 px-4 py-2.5 text-[15px] leading-[1.55] text-text-primary sm:max-w-[80%]">
          {turn.question}
        </p>
      </div>

      <div className="mt-5 flex gap-3.5">
        <span className="mt-0.5 grid h-8 w-8 flex-none place-items-center rounded-full border border-border-subtle bg-surface-1 shadow-sm" aria-hidden="true">
          <TopologyMark variant="mark" size={18} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="mb-1.5 text-[13px] font-semibold text-text-primary">CodeSage</p>

          {turn.status === "thinking" && <ThinkingSteps stage={turn.stage} startedAt={turn.askedAt} onCancel={onCancel} />}

          {turn.status === "error" && err && (
            <Notice
              tone={err.message === "Cancelled." ? "info" : "bad"}
              title={
                err instanceof ApiError
                  ? err.status === 504
                    ? "This question took too long"
                    : err.kind === "network"
                      ? "Can't reach the CodeSage backend"
                      : err.status === 409
                        ? "The knowledge index isn't ready"
                        : "The AI pipeline failed"
                  : err.message === "Cancelled."
                    ? "Stopped"
                    : "Something went wrong answering this question"
              }
              actions={
                <Button size="sm" variant="secondary" onClick={onRetry}>
                  <RefreshCw size={13} aria-hidden="true" />
                  {err.message === "Cancelled." ? "Ask again" : "Retry"}
                </Button>
              }
            >
              {err.message !== "Cancelled." && (
                <div className="cs-errmono">
                  {err instanceof ApiError && err.status ? `HTTP ${err.status} · ` : ""}
                  {err.message}
                </div>
              )}
            </Notice>
          )}

          {turn.status === "revealing" && (
            <div className={cn("cs-prose whitespace-pre-line", muted && "cs-prose-muted")} aria-busy="true">
              {plainText(turn.partial)}
              <span className="cs-caret" aria-hidden="true">
                ▍
              </span>
            </div>
          )}

          {turn.status === "done" && res && (
            <>
              <AnswerProse text={res.answer} evidence={ev} hovered={hovered} onHover={onHover} onCite={onCite} muted={muted} />

              {ev.length > 0 ? (
                <div className="mt-5">
                  <p className="mb-2 text-[12.5px] font-medium text-text-tertiary">Sources ({ev.length})</p>
                  <div className="flex flex-wrap gap-2">
                    {sources.map((c, i) => (
                      <SourceChip key={`${c.file_path}-${i}`} c={c} index={i} active={hovered === i} onCite={onCite} onHover={onHover} />
                    ))}
                    {ev.length > VISIBLE_SOURCES && (
                      <button
                        type="button"
                        onClick={() => setShowAll((v) => !v)}
                        className="inline-flex items-center rounded-[8px] px-2.5 py-1.5 text-[12.5px] font-medium text-text-tertiary hover:bg-surface-2 hover:text-text-primary"
                      >
                        {showAll ? "Show fewer" : `+${ev.length - VISIBLE_SOURCES} more`}
                      </button>
                    )}
                  </div>
                </div>
              ) : (
                <p className="mt-4 text-small text-text-tertiary">No citations — nothing in the index cleared the relevance floor.</p>
              )}

              <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2">
                <VerificationBadge status={res.verification.status} />
                {res.verification.reasons[0] && <span className="text-[13px] text-text-secondary">{res.verification.reasons[0]}</span>}
              </div>

              <div className="-ml-2.5 mt-2.5 flex flex-wrap items-center gap-0.5">
                <CopyButton text={plainText(res.answer)} />
                <button type="button" className={actionClass} onClick={onRetry}>
                  <RefreshCw size={14} aria-hidden="true" />
                  Regenerate
                </button>
                <button type="button" className={actionClass} onClick={() => setOpen((v) => !v)} aria-expanded={open}>
                  <Info size={14} aria-hidden="true" />
                  How this was answered
                  <ChevronDown size={13} className={cn("transition-transform", open && "rotate-180")} aria-hidden="true" />
                </button>
              </div>
              {open && <Disclosure res={res} />}

              {(hint || followUps.length > 0) && (
                <div className="mt-4 flex flex-col gap-2.5">
                  {hint && (
                    <p className="inline-flex items-center gap-1.5 text-[13px] text-text-secondary">
                      <Info size={14} aria-hidden="true" />
                      {hint}
                    </p>
                  )}
                  {followUps.length > 0 && (
                    <div>
                      <p className="mb-2 text-[12.5px] font-medium text-text-tertiary">Related questions</p>
                      <div className="flex flex-wrap gap-2">
                        {followUps.map((q) => (
                          <button key={q} type="button" className="cs-qchip" onClick={() => onFollowUp(q)}>
                            {q}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </article>
  );
}
