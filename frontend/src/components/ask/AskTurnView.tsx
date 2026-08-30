"use client";

import { useState } from "react";
import { ReasoningRibbon, ReasoningRibbonLabels } from "@/components/devices/ReasoningRibbon";
import { EvidenceTrail } from "@/components/devices/EvidenceTrail";
import { VerificationBadge } from "@/components/domain/GroundingBadges";
import type { AskTurn } from "@/hooks/useAskStream";
import { useMediaQuery } from "@/hooks/useMediaQuery";

/**
 * Ask CodeSage's turn view (Design System §16): no chat-bubble chrome. A
 * question is a quiet, right-set italic line; the answer is flowing prose
 * marked by the Reasoning Ribbon and a violet identity rule, with the
 * Evidence Trail tethering citations beneath.
 */
export function AskTurnView({ turn }: { turn: AskTurn }) {
  const [disclosureOpen, setDisclosureOpen] = useState(false);
  const compactTrail = useMediaQuery("(max-width: 899px)");
  const [primary, ...rest] = turn.citations;

  return (
    <div className="flex flex-col gap-7">
      <div className="text-right">
        <div className="cs-mono-label mb-1.5">QUESTION</div>
        <div className="font-display text-lede italic text-[oklch(0.8_0.01_280)]">{turn.question}</div>
      </div>

      <div className="flex gap-4">
        <ReasoningRibbon stageStates={turn.stageStates} finalStatus={turn.verification?.status} />
        <div className="flex flex-1 flex-col gap-3.5 border-l-[1.5px] border-violet/30 pl-4">
          <ReasoningRibbonLabels stageStates={turn.stageStates} finalStatus={turn.verification?.status} />

          {turn.status === "error" ? (
            <p className="text-body text-danger">{turn.errorMessage}</p>
          ) : (
            <p className="text-[15px] leading-[1.85] text-text-primary/90">
              {turn.answerText}
              {turn.status === "streaming" && <span className="animate-pulse text-violet">▍</span>}
            </p>
          )}

          {primary && (
            <EvidenceTrail primary compact={compactTrail}>
              {citationLabel(primary)} <span className="text-text-tertiary">&middot; primary</span>
            </EvidenceTrail>
          )}
          {rest.length > 0 && (
            <div className="flex flex-wrap gap-4 pl-0.5">
              {rest.map((c, i) => (
                <span key={i} className="font-mono text-[10.5px] text-text-tertiary">
                  {citationLabel(c)}
                </span>
              ))}
            </div>
          )}

          {turn.verification && (
            <div className="flex items-center gap-4">
              <VerificationBadge status={turn.verification.status} />
              {turn.metadata && (
                <button
                  onClick={() => setDisclosureOpen((v) => !v)}
                  className="font-mono text-[10.5px] text-text-tertiary hover:text-text-secondary"
                  aria-expanded={disclosureOpen}
                >
                  how this was answered {disclosureOpen ? "▴" : "▾"}
                </button>
              )}
            </div>
          )}

          {disclosureOpen && turn.metadata && (
            <dl className="grid max-w-[380px] grid-cols-2 gap-x-4 gap-y-1.5 border-t border-border-subtle pt-3 font-mono text-[10.5px]">
              <dt className="text-text-tertiary">intent</dt>
              <dd className="text-text-secondary">{turn.metadata.intent}</dd>
              <dt className="text-text-tertiary">provider</dt>
              <dd className="text-text-secondary">{turn.metadata.provider} / {turn.metadata.model}</dd>
              <dt className="text-text-tertiary">cache</dt>
              <dd className="text-text-secondary">
                {turn.metadata.cache_hit ? "hit" : "miss"} ({turn.metadata.stage_latency_ms.total_ms}ms)
              </dd>
              {/* On a cache hit, the backend's per-stage breakdown reflects
                  the ORIGINAL generation that populated the cache, not this
                  response's own (near-instant) latency — showing it next to
                  a small total would read as a data error. Design System
                  §9.3's own cache-disclosure rule ("cache: hit (19ms)")
                  already covers the cache case fully; the stage breakdown
                  is only meaningful, and only shown, for a fresh miss. */}
              {!turn.metadata.cache_hit && (
                <>
                  <dt className="text-text-tertiary">retrieval</dt>
                  <dd className="text-text-secondary">{turn.metadata.stage_latency_ms.retrieval_ms}ms</dd>
                  <dt className="text-text-tertiary">reasoning</dt>
                  <dd className="text-text-secondary">{turn.metadata.stage_latency_ms.llm_ms}ms</dd>
                </>
              )}
            </dl>
          )}
        </div>
      </div>
    </div>
  );
}

function citationLabel(c: AskTurn["citations"][number]): string {
  const range = c.start_line && c.end_line ? `:${c.start_line}–${c.end_line}` : "";
  return `${c.file_path}${range}`;
}
