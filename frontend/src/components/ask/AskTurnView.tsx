"use client";

import { useState } from "react";
import { ChevronDown, Info, RefreshCw } from "lucide-react";
import { AnswerProse } from "@/components/ask/AnswerProse";
import { STAGE_DESCRIPTIONS, loc } from "@/components/ask/EvidenceRail";
import { EvidenceTrail } from "@/components/devices/EvidenceTrail";
import { ReasoningRibbon, type StageState } from "@/components/devices/ReasoningRibbon";
import { VerificationBadge } from "@/components/domain/GroundingBadges";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/state/StateVocabulary";
import { plainText } from "@/lib/answerFormat";
import { ApiError } from "@/lib/api/client";
import type { AskTurn } from "@/lib/askSession";
import { mapStageLatencyToRibbon, RIBBON_STAGE_ORDER, ribbonOverheadMs, type RibbonStageKey } from "@/lib/reasoningRibbon";
import type { AskResponseData } from "@/lib/types/ai";
import { cn } from "@/lib/utils";

function stageStates(turn: AskTurn): Record<RibbonStageKey, StageState> {
  const out = {} as Record<RibbonStageKey, StageState>;
  RIBBON_STAGE_ORDER.forEach((k, i) => {
    if (turn.status === "done" || turn.status === "revealing") out[k] = "done";
    else if (turn.status === "error") out[k] = i < turn.stage ? "done" : "pending";
    else out[k] = i < turn.stage ? "done" : i === turn.stage ? "active" : "pending";
  });
  if (turn.response && turn.response.metadata.stage_latency_ms.llm_ms === 0 && !turn.response.metadata.cache_hit) {
    out.reason = "skipped";
  }
  return out;
}

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
    <div className="cs-panel cs-fade-in mt-3.5 px-[18px] py-4">
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
        // On a cache hit the backend's per-stage breakdown belongs to the
        // original generation, not this fast response — hide it (known limitation L6).
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
      <p className="cs-mono-label mt-4">Verification</p>
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

/**
 * One Ask turn (Design System §16): no chat bubbles. The question is a
 * right-set italic line; CodeSage's answer is prose behind the violet
 * voice rule, with the Reasoning Ribbon beside it and every citation
 * linked to the evidence rail.
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
  const res = turn.response;
  const states = stageStates(turn);
  const ms = res && !res.metadata.cache_hit ? mapStageLatencyToRibbon(res.metadata.stage_latency_ms) : undefined;
  const status = res?.verification.status;
  const muted = status === "contradicted";
  const ev = res?.evidence ?? [];
  const hint =
    status === "insufficient_evidence"
      ? "Name a specific file, symbol or module"
      : status === "contradicted"
        ? "Ask about a more specific file, symbol or module"
        : null;
  const followUps =
    status === "supported" || status === "partially_supported"
      ? (res?.relevant_files ?? []).slice(0, 2).map((f) => `Explain ${f}`).filter((q) => q.toLowerCase() !== turn.question.toLowerCase())
      : [];
  const err = turn.error;

  return (
    <article className="mt-11 scroll-mt-5 first:mt-7" aria-label={`Question: ${turn.question}`}>
      <div className="flex flex-col items-end gap-1.5 text-right">
        <span className="cs-mono-label inline-flex items-center gap-2.5 before:inline-block before:h-px before:w-5 before:bg-border-strong">Question</span>
        <p className="max-w-[52ch] font-display text-[19px] italic leading-[1.42] text-text-primary sm:text-[21px]">{turn.question}</p>
      </div>
      <div className="mt-5 grid grid-cols-1 gap-3.5 sm:grid-cols-[96px_minmax(0,1fr)]">
        <ReasoningRibbon
          stageStates={states}
          stageMs={ms}
          finalStatus={status}
          cached={res?.metadata.cache_hit}
          className="hidden sm:flex"
        />
        <ReasoningRibbon
          stageStates={states}
          stageMs={ms}
          finalStatus={status}
          cached={res?.metadata.cache_hit}
          orientation="horizontal"
          className="sm:hidden"
        />
        <div className="cs-voice min-w-0">
          {turn.status === "thinking" && (
            <div role="status">
              <div className="flex items-center gap-2.5 font-mono text-[12px] text-violet">
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-[1.5px] border-current border-r-transparent" aria-hidden="true" />
                {STAGE_DESCRIPTIONS[Math.min(turn.stage, 3)]}
              </div>
              <div className="cs-skel mt-4 h-3.5 w-[92%]" />
              <div className="cs-skel mt-2 h-3.5 w-[78%]" />
              <div className="cs-skel mt-2 h-3.5 w-[60%]" />
              <button onClick={onCancel} className="cs-disclosure-btn mt-3">
                cancel
              </button>
            </div>
          )}
          {turn.status === "error" && err && (
            <Notice
              tone="bad"
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
                    ? "Cancelled"
                    : "Something went wrong answering this question"
              }
              actions={
                <Button size="sm" variant="secondary" onClick={onRetry}>
                  <RefreshCw size={13} aria-hidden="true" />
                  Retry
                </Button>
              }
            >
              <div className="cs-errmono">
                {err instanceof ApiError && err.status ? `HTTP ${err.status} · ` : ""}
                {err.message}
              </div>
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
              {ev[0] && (
                <div
                  className="-ml-3 mt-[18px] rounded-[8px] bg-[linear-gradient(90deg,oklch(0.75_0.13_300/0.06),transparent_75%)] px-3 py-2.5"
                  onMouseEnter={() => onHover(0)}
                  onMouseLeave={() => onHover(null)}
                >
                  <EvidenceTrail primary>
                    <button className="text-left text-text-primary hover:text-[var(--cs-accent-violet-hover)]" onClick={() => onCite(0)} aria-label={`Primary evidence ${loc(ev[0])}`}>
                      {loc(ev[0])}
                    </button>{" "}
                    <span className="text-text-tertiary">· primary</span>
                  </EvidenceTrail>
                </div>
              )}
              {ev.length > 1 && (
                <div className="mt-2.5 flex flex-wrap gap-x-3.5 gap-y-1 pl-[11px]">
                  {ev.slice(1).map((c, j) => (
                    <button
                      key={`${c.file_path}-${j}`}
                      onClick={() => onCite(j + 1)}
                      onMouseEnter={() => onHover(j + 1)}
                      onMouseLeave={() => onHover(null)}
                      className={cn(
                        "break-all rounded text-left font-mono text-[11.5px] transition-colors",
                        hovered === j + 1 ? "text-text-primary" : "text-text-tertiary hover:text-text-primary",
                      )}
                    >
                      <sup className="mr-0.5 text-[9px] text-violet">{j + 2}</sup>
                      {loc(c)}
                    </button>
                  ))}
                </div>
              )}
              {ev.length === 0 && <p className="mt-3 text-small text-text-tertiary">No citations — nothing in the index cleared the relevance floor.</p>}
              <div className="mt-[18px] flex flex-wrap items-center gap-x-[18px] gap-y-3 border-t border-border-subtle pt-4">
                <VerificationBadge status={res.verification.status} />
                <span className="text-small text-text-secondary">{res.verification.reasons[0]}</span>
                <button onClick={() => setOpen((v) => !v)} aria-expanded={open} className="cs-disclosure-btn">
                  how this was answered <ChevronDown size={12} aria-hidden="true" />
                </button>
              </div>
              {open && <Disclosure res={res} />}
              {(hint || followUps.length > 0) && (
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  {hint && (
                    <span className="inline-flex items-center gap-1.5 font-mono text-[11.5px] text-text-secondary">
                      <Info size={13} aria-hidden="true" />
                      {hint}
                    </span>
                  )}
                  {followUps.length > 0 && (
                    <>
                      <span className="cs-tag text-text-tertiary" title="Generated from the answer's relevant files — the backend returns no suggestions">
                        Suggested
                      </span>
                      {followUps.map((q) => (
                        <button key={q} className="cs-qchip" onClick={() => onFollowUp(q)}>
                          {q}
                        </button>
                      ))}
                    </>
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
