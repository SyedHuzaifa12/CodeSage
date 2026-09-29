"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ChevronDown, Layers, Send } from "lucide-react";
import { useRepositoryContext } from "@/context/RepositoryContext";
import { RequireReady } from "@/components/nav/RequireReady";
import { AskTurnView } from "@/components/ask/AskTurnView";
import { EvidenceRail } from "@/components/ask/EvidenceRail";
import { Modal } from "@/components/ui/Modal";
import { useAskStream } from "@/hooks/useAskStream";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { fileToModule } from "@/lib/graphModel";
import { useIntelligence, useSymbols } from "@/lib/query/workspace";
import type { AskOptions } from "@/lib/types/ai";

const ALL_SOURCES = ["semantic", "lexical", "structural"] as const;

function AskInner() {
  const { repositoryId } = useRepositoryContext();
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const intelligence = useIntelligence(repositoryId);
  const symbols = useSymbols(repositoryId);
  const { turns, ask, cancel, clear } = useAskStream(repositoryId);
  const isDesktop = useMediaQuery("(min-width: 1280px)");
  const [draft, setDraft] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [topK, setTopK] = useState("");
  const [sources, setSources] = useState<string[]>([...ALL_SOURCES]);
  const [forceRefresh, setForceRefresh] = useState(false);
  const [selectedTurn, setSelectedTurn] = useState<string | null>(null);
  const [openEvidence, setOpenEvidence] = useState<number | null>(null);
  const [hovered, setHovered] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const deepLinked = useRef(false);

  const busy = turns.some((t) => t.status === "thinking" || t.status === "revealing");
  const railTurn = turns.find((t) => t.id === selectedTurn) ?? turns[turns.length - 1];

  const options = (): AskOptions | undefined => {
    const o: AskOptions = {};
    if (topK) o.top_k = Number(topK);
    if (sources.length < ALL_SOURCES.length) o.sources = sources;
    if (forceRefresh) o.force_refresh = true;
    return Object.keys(o).length ? o : undefined;
  };

  function submit(q: string) {
    const text = q.trim();
    if (!text || busy || sources.length === 0) return;
    setSelectedTurn(null);
    setOpenEvidence(null);
    ask(text, options());
  }

  useEffect(() => {
    const q = searchParams.get("q");
    if (q && !deepLinked.current) {
      deepLinked.current = true;
      router.replace(pathname);
      if (!busy) ask(q);
    }
  }, [searchParams, router, pathname, ask, busy]);

  const lastStatus = turns[turns.length - 1]?.status;
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [turns.length, lastStatus]);

  useEffect(() => {
    if (!busy) inputRef.current?.focus({ preventScroll: true });
  }, [busy]);

  const suggestions = useMemo(() => {
    const I = intelligence.data;
    const out = ["Explain the architecture of this repository"];
    const hot = I?.dependency_hotspots[0];
    if (hot) {
      const file = symbols.data?.symbols.find((s) => fileToModule(s.file_path) === hot.module_path)?.file_path;
      out.push(`Which modules depend on ${file ?? hot.module_path}?`);
    }
    if (I?.largest_modules[0]) out.push(`What would be affected if I change ${I.largest_modules[0].path}?`);
    out.push("Where are the tests?", "How is configuration loaded?");
    return out;
  }, [intelligence.data, symbols.data]);

  function cite(turnId: string, i: number) {
    setSelectedTurn(turnId);
    setOpenEvidence(i);
    if (!isDesktop) setDrawerOpen(true);
    else requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-ev="${i}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
  }

  const rail = (
    <EvidenceRail
      turn={railTurn}
      repositoryId={repositoryId}
      symbols={symbols.data?.symbols}
      openIndex={openEvidence}
      hovered={railTurn && (selectedTurn === null || selectedTurn === railTurn.id) ? hovered : null}
      onToggle={(i) => setOpenEvidence((v) => (v === i ? null : i))}
      onHover={setHovered}
    />
  );

  return (
    <div className="grid h-full min-h-0 grid-cols-1 xl:grid-cols-[minmax(0,1fr)_300px]">
      <div className="flex h-full min-h-0 flex-col overflow-hidden">
        <div ref={scrollRef} className="cs-scrollbar min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[740px] px-4 pb-9 pt-8 sm:px-8">
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <h1 className="cs-display">Ask CodeSage</h1>
              <div className="flex items-center gap-1.5">
                {intelligence.data && (
                  <span className="cs-monoline mr-2 !text-[11px]">reasoning over {intelligence.data.total_symbols.toLocaleString("en-US")} symbols</span>
                )}
                {!isDesktop && turns.length > 0 && (
                  <button className="cs-chipbtn" onClick={() => setDrawerOpen(true)}>
                    <Layers size={13} aria-hidden="true" />
                    Evidence
                  </button>
                )}
                {turns.length > 0 && (
                  <button className="cs-chipbtn" onClick={() => { clear(); setSelectedTurn(null); setOpenEvidence(null); }} disabled={busy}>
                    New conversation
                  </button>
                )}
              </div>
            </div>
            <p className="mt-1 text-small text-text-tertiary">Session only — each question is answered independently, and turns are gone on reload.</p>

            {turns.length === 0 && (
              <div className="pb-2 pt-11">
                <p className="cs-lede">Ask your first question — CodeSage grounds every answer in retrieved evidence from this repository.</p>
                <p className="cs-mono-label mt-8">Try</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {suggestions.map((s) => (
                    <button key={s} className="cs-qchip" onClick={() => submit(s)}>
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {turns.map((t) => (
              <div key={t.id} onClickCapture={() => setSelectedTurn(t.id)}>
                <AskTurnView
                  turn={t}
                  hovered={railTurn?.id === t.id ? hovered : null}
                  onHover={(i) => { setSelectedTurn(t.id); setHovered(i); }}
                  onCite={(i) => cite(t.id, i)}
                  onRetry={() => ask(t.question, options(), t.id)}
                  onCancel={() => cancel(t.id)}
                  onFollowUp={submit}
                />
              </div>
            ))}
          </div>
        </div>

        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            const v = draft;
            setDraft("");
            submit(v);
          }}
          className="flex-none border-t border-border-subtle bg-[linear-gradient(180deg,oklch(0.15_0.006_280/0.85),var(--cs-bg))] backdrop-blur-[10px]"
        >
          <div className="mx-auto max-w-[740px] px-3.5 pb-3.5 pt-3 sm:px-8">
            <div className="flex items-center gap-3">
              <label htmlFor="ask-input" className="sr-only">
                Ask about this repository
              </label>
              <input
                id="ask-input"
                ref={inputRef}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Ask about this repository…"
                autoComplete="off"
                className="cs-underline-input h-12 font-display text-[19px] italic"
              />
              <button
                type="submit"
                aria-label="Send question"
                disabled={busy || !draft.trim() || sources.length === 0}
                className="group grid h-10 w-10 flex-none place-items-center rounded-full bg-[linear-gradient(180deg,oklch(0.82_0.12_300),oklch(0.72_0.135_300))] text-[oklch(0.18_0.03_300)] shadow-[inset_0_1px_0_oklch(1_0_0/0.35),inset_0_0_0_1px_oklch(0.62_0.13_300/0.5)] transition-transform enabled:active:scale-95 disabled:cursor-not-allowed disabled:opacity-30"
              >
                <Send size={16} className="transition-transform group-enabled:group-hover:translate-x-0.5" aria-hidden="true" />
              </button>
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1">
              <button type="button" onClick={() => setAdvancedOpen((v) => !v)} aria-expanded={advancedOpen} className="cs-disclosure-btn">
                advanced <ChevronDown size={12} aria-hidden="true" />
              </button>
              <span className="text-small text-text-tertiary">Enter to send</span>
              {(topK || sources.length < 3 || forceRefresh) && !advancedOpen && (
                <span className="font-mono text-[10.5px] text-violet">custom retrieval options active</span>
              )}
            </div>
            {advancedOpen && (
              <div className="cs-fade-in flex flex-wrap items-center gap-x-[22px] gap-y-3 pb-1 pt-3 text-[12px] text-text-secondary">
                <label className="flex items-center gap-2">
                  top_k
                  <input
                    type="number"
                    min={1}
                    max={50}
                    placeholder="auto"
                    value={topK}
                    onChange={(e) => setTopK(e.target.value)}
                    className="h-[30px] w-[70px] rounded-[7px] border border-border-strong bg-surface-1 px-2 font-mono text-[12px] text-text-primary !outline-none focus:border-violet"
                  />
                </label>
                <span className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Retrieval sources">
                  sources
                  {ALL_SOURCES.map((s) => (
                    <button
                      key={s}
                      type="button"
                      className="cs-chipbtn"
                      aria-pressed={sources.includes(s)}
                      onClick={() => setSources((cur) => (cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]))}
                    >
                      {s}
                    </button>
                  ))}
                </span>
                <label className="flex cursor-pointer items-center gap-2">
                  <input type="checkbox" checked={forceRefresh} onChange={(e) => setForceRefresh(e.target.checked)} className="accent-[var(--cs-accent-violet)]" />
                  force refresh <span className="text-text-tertiary">(bypass the answer cache)</span>
                </label>
                {sources.length === 0 && <span className="text-warning">Select at least one source.</span>}
              </div>
            )}
          </div>
        </form>
      </div>

      {isDesktop && (
        <aside aria-label="Evidence for the selected answer" className="cs-scrollbar hidden h-full min-h-0 overflow-y-auto border-l border-border-subtle bg-[linear-gradient(180deg,oklch(0.163_0.007_280),var(--cs-bg)_55%)] px-5 pb-10 pt-7 xl:block">
          {rail}
        </aside>
      )}
      {!isDesktop && (
        <Modal open={drawerOpen} onOpenChange={setDrawerOpen} title="Evidence" side="right">
          {rail}
        </Modal>
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
