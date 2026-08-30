"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useSearchParams } from "next/navigation";
import { useRepositoryContext } from "@/context/RepositoryContext";
import { RequireReady } from "@/components/nav/RequireReady";
import { AskTurnView } from "@/components/ask/AskTurnView";
import { Input } from "@/components/ui/Input";
import { EmptyState } from "@/components/state/StateVocabulary";
import { useAskStream } from "@/hooks/useAskStream";
import { useIntelligence } from "@/lib/query/workspace";
import { useMediaQuery } from "@/hooks/useMediaQuery";

function AskInner() {
  const { repositoryId } = useRepositoryContext();
  const searchParams = useSearchParams();
  const intelligence = useIntelligence(repositoryId);
  const { turns, ask } = useAskStream(repositoryId);
  const [draft, setDraft] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [topK, setTopK] = useState<string>("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const askedInitialQuery = useRef(false);
  const isDesktop = useMediaQuery("(min-width: 1280px)");

  useEffect(() => {
    const q = searchParams.get("q");
    if (q && !askedInitialQuery.current) {
      askedInitialQuery.current = true;
      ask(q);
    }
  }, [searchParams, ask]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns]);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!draft.trim()) return;
    ask(draft.trim(), topK ? { top_k: Number(topK) } : undefined);
    setDraft("");
  }

  const lastTurn = turns[turns.length - 1];
  const uniqueFiles = new Set(lastTurn?.citations.map((c) => c.file_path));
  const uniqueSources = new Set(lastTurn?.citations.flatMap((c) => c.retrieval_sources));

  return (
    <div className="flex h-[calc(100vh-56px)] gap-11 px-11">
      <div className="flex max-w-[700px] flex-1 flex-col">
        <div className="flex items-baseline justify-between border-b border-border-subtle py-4">
          <h1 className="font-display text-display italic text-text-primary">Ask CodeSage</h1>
          {intelligence.data && (
            <div className="font-mono text-[9.5px] text-text-tertiary">
              reasoning over {intelligence.data.total_symbols.toLocaleString()} symbols
            </div>
          )}
        </div>

        <div ref={scrollRef} className="flex-1 cs-scrollbar overflow-y-auto py-6">
          {turns.length === 0 && (
            <EmptyState message="Ask your first question — CodeSage grounds every answer in retrieved evidence from this repository." />
          )}
          <div className="flex flex-col gap-9">
            {turns.map((turn) => (
              <AskTurnView key={turn.id} turn={turn} />
            ))}
          </div>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-2 border-t border-border-subtle py-4">
          <div className="flex items-center gap-3.5">
            <Input
              editorial
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Ask about this repository…"
              aria-label="Ask CodeSage a question"
            />
            <button
              type="button"
              onClick={() => setAdvancedOpen((v) => !v)}
              className="font-mono text-[10px] text-text-tertiary hover:text-text-secondary"
            >
              advanced
            </button>
            <button type="submit" aria-label="Submit question" className="text-violet">
              <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
                <path d="M4 12l16-8-6 8 6 8z" />
              </svg>
            </button>
          </div>
          {advancedOpen && (
            <div className="flex items-center gap-2 font-mono text-[10.5px] text-text-tertiary">
              <label htmlFor="ask-topk">top_k override</label>
              <input
                id="ask-topk"
                type="number"
                min={1}
                value={topK}
                onChange={(e) => setTopK(e.target.value)}
                className="w-16 rounded-sm border border-border-strong bg-surface-1 px-1.5 py-0.5 text-text-primary"
              />
            </div>
          )}
        </form>
      </div>

      {isDesktop && (
        <aside className="w-[270px] flex-shrink-0 py-6">
          <div className="cs-mono-label mb-2.5">CONTEXT APERTURE</div>
          <svg width={70} height={44} viewBox="0 0 70 44" aria-hidden="true">
            <path d="M35,42 L10,6" stroke="oklch(0.75 0.13 300 / 0.5)" />
            <path d="M35,42 L35,2" stroke="oklch(0.75 0.13 300 / 0.5)" />
            <path d="M35,42 L60,6" stroke="oklch(0.75 0.13 300 / 0.5)" />
            <path d="M14,10 A32,32 0 0 1 56,10" fill="none" stroke="oklch(0.75 0.13 300)" strokeWidth={1.6} />
          </svg>
          <div className="mt-1.5 font-mono text-[10px] text-text-tertiary">
            {lastTurn ? `${uniqueFiles.size} file${uniqueFiles.size === 1 ? "" : "s"} · ${[...uniqueSources].join(" + ") || "—"}` : "no answer yet"}
          </div>

          {lastTurn?.citations[0] && (
            <div className="mt-4.5 border-t border-border-subtle pt-4">
              <div className="cs-mono-label mb-2">PRIMARY EVIDENCE</div>
              <div className="font-mono text-[10.5px] text-text-secondary">
                {lastTurn.citations[0].file_path}
                {lastTurn.citations[0].start_line ? `:${lastTurn.citations[0].start_line}–${lastTurn.citations[0].end_line}` : ""}
              </div>
              {lastTurn.citations[0].symbol_name && (
                <div className="mt-1 font-mono text-[10.5px] text-text-tertiary">
                  {lastTurn.citations[0].symbol_type} {lastTurn.citations[0].symbol_name}
                </div>
              )}
              <div className="mt-1 font-mono text-[10px] text-text-tertiary">
                score {lastTurn.citations[0].retrieval_score.toFixed(2)} &middot; {lastTurn.citations[0].retrieval_sources.join(", ")}
              </div>
            </div>
          )}
        </aside>
      )}
    </div>
  );
}

export default function AskPage() {
  return (
    <RequireReady>
      <AskInner />
    </RequireReady>
  );
}
