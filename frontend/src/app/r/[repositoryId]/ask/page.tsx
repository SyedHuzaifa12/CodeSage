"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ArrowDown, Layers, PanelRight, Plus } from "lucide-react";
import { useRepositoryContext } from "@/context/RepositoryContext";
import { RequireReady } from "@/components/nav/RequireReady";
import { AskTurnView } from "@/components/ask/AskTurnView";
import { Composer, type ComposerHandle } from "@/components/ask/Composer";
import { EmptyChat } from "@/components/ask/EmptyChat";
import { EvidenceRail } from "@/components/ask/EvidenceRail";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { useAskStream } from "@/hooks/useAskStream";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { fileToModule } from "@/lib/graphModel";
import { useIntelligence, useSymbols } from "@/lib/query/workspace";
import type { AskOptions } from "@/lib/types/ai";
import { cn } from "@/lib/utils";

const ALL_SOURCES = ["semantic", "lexical", "structural"] as const;
const NEAR_BOTTOM_PX = 96;

function AskInner() {
  const { repositoryId, repository } = useRepositoryContext();
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const intelligence = useIntelligence(repositoryId);
  const symbols = useSymbols(repositoryId);
  const { turns, ask, cancel, clear } = useAskStream(repositoryId);
  const isDesktop = useMediaQuery("(min-width: 1280px)");
  const [draft, setDraft] = useState("");
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [topK, setTopK] = useState("");
  const [sources, setSources] = useState<string[]>([...ALL_SOURCES]);
  const [forceRefresh, setForceRefresh] = useState(false);
  const [selectedTurn, setSelectedTurn] = useState<string | null>(null);
  const [openEvidence, setOpenEvidence] = useState<number | null>(null);
  const [hovered, setHovered] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [railOpen, setRailOpen] = useState(true);
  const [atBottom, setAtBottom] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<ComposerHandle>(null);
  const stickToBottom = useRef(true);
  const deepLinked = useRef(false);

  const busy = turns.some((t) => t.status === "thinking" || t.status === "revealing");
  const activeTurn = turns.find((t) => t.status === "thinking" || t.status === "revealing");
  const railTurn = turns.find((t) => t.id === selectedTurn) ?? turns[turns.length - 1];
  const showRail = isDesktop && railOpen;
  const optionsActive = Boolean(topK) || sources.length < ALL_SOURCES.length || forceRefresh;

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
    stickToBottom.current = true; // a new question always brings the view to the new exchange
    setSelectedTurn(null);
    setOpenEvidence(null);
    ask(text, options());
  }

  function send() {
    const v = draft;
    setDraft("");
    submit(v);
  }

  useEffect(() => {
    const q = searchParams.get("q");
    if (q && !deepLinked.current) {
      deepLinked.current = true;
      router.replace(pathname);
      if (!busy) ask(q);
    }
  }, [searchParams, router, pathname, ask, busy]);

  // Follow the answer as it is written, but stop following the moment the user scrolls up to read.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottom.current) el.scrollTo({ top: el.scrollHeight, behavior: busy ? "auto" : "smooth" });
  }, [turns, busy]);

  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX;
    stickToBottom.current = near;
    setAtBottom(near);
  }

  function jumpToLatest() {
    stickToBottom.current = true;
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }

  useEffect(() => {
    if (!busy) composerRef.current?.focus();
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
    else {
      setRailOpen(true);
      requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-ev="${i}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
    }
  }

  function newChat() {
    clear();
    setSelectedTurn(null);
    setOpenEvidence(null);
    setDraft("");
    stickToBottom.current = true;
    composerRef.current?.focus();
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

  const optionsPanel = (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-3 text-[13px] text-text-secondary">
      <label className="flex items-center gap-2">
        Max evidence items
        <input
          type="number"
          min={1}
          max={50}
          placeholder="auto"
          value={topK}
          onChange={(e) => setTopK(e.target.value)}
          className="h-8 w-[72px] rounded-[8px] border border-border-strong bg-surface-1 px-2 font-mono text-[12.5px] text-text-primary focus:border-violet focus:outline-none"
        />
      </label>
      <span className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Retrieval sources">
        Search by
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
        Skip the answer cache
      </label>
      {sources.length === 0 && <span className="font-medium text-warning">Select at least one source.</span>}
    </div>
  );

  return (
    <div className={cn("grid h-full min-h-0 grid-cols-1", showRail && "xl:grid-cols-[minmax(0,1fr)_330px]")}>
      <div className="flex h-full min-h-0 flex-col overflow-hidden">
        <header className="flex h-12 flex-none items-center justify-between gap-3 border-b border-border-subtle px-4 sm:px-6">
          <div className="flex min-w-0 items-baseline gap-2.5">
            <h1 className="truncate text-[15px] font-semibold text-text-primary">Ask CodeSage</h1>
            {intelligence.data && (
              <span className="hidden truncate text-[12.5px] text-text-tertiary sm:inline">
                {repository?.name ? `${repository.name} · ` : ""}
                {intelligence.data.total_symbols.toLocaleString("en-US")} symbols indexed
              </span>
            )}
          </div>
          <div className="flex flex-none items-center gap-1.5">
            {isDesktop ? (
              <button
                type="button"
                onClick={() => setRailOpen((v) => !v)}
                aria-pressed={railOpen}
                aria-label={railOpen ? "Hide sources panel" : "Show sources panel"}
                title={railOpen ? "Hide sources panel" : "Show sources panel"}
                className={cn("grid h-8 w-8 place-items-center rounded-[8px] text-text-tertiary transition-colors hover:bg-surface-2 hover:text-text-primary", railOpen && "bg-surface-2 text-text-primary")}
              >
                <PanelRight size={16} strokeWidth={1.7} aria-hidden="true" />
              </button>
            ) : (
              turns.length > 0 && (
                <Button size="sm" variant="ghost" onClick={() => setDrawerOpen(true)}>
                  <Layers size={14} aria-hidden="true" />
                  Sources
                </Button>
              )
            )}
            <Button size="sm" variant="secondary" onClick={newChat} disabled={busy || turns.length === 0}>
              <Plus size={14} aria-hidden="true" />
              New chat
            </Button>
          </div>
        </header>

        <div className="relative min-h-0 flex-1">
          <div ref={scrollRef} onScroll={onScroll} className="cs-scrollbar h-full overflow-y-auto" aria-live="off">
            <div className="mx-auto max-w-[760px] px-4 pb-8 pt-6 sm:px-6">
              {turns.length === 0 ? (
                <EmptyChat
                  repositoryName={repository?.name}
                  symbolCount={intelligence.data?.total_symbols}
                  suggestions={suggestions}
                  onPick={(q) => submit(q)}
                />
              ) : (
                turns.map((t) => (
                  <div key={t.id} onClickCapture={() => setSelectedTurn(t.id)}>
                    <AskTurnView
                      turn={t}
                      hovered={railTurn?.id === t.id ? hovered : null}
                      onHover={(i) => {
                        setSelectedTurn(t.id);
                        setHovered(i);
                      }}
                      onCite={(i) => cite(t.id, i)}
                      onRetry={() => ask(t.question, options(), t.id)}
                      onCancel={() => cancel(t.id)}
                      onFollowUp={submit}
                    />
                  </div>
                ))
              )}
            </div>
          </div>
          {!atBottom && turns.length > 0 && (
            <button
              type="button"
              onClick={jumpToLatest}
              aria-label="Jump to the latest message"
              className="cs-fade-in absolute bottom-3 left-1/2 grid h-9 w-9 -translate-x-1/2 place-items-center rounded-full border border-border-strong bg-surface-1 text-text-secondary shadow-md transition-colors hover:text-text-primary"
            >
              <ArrowDown size={16} aria-hidden="true" />
            </button>
          )}
        </div>

        <div className="flex-none px-3.5 pb-3 pt-1 sm:px-6">
          <div className="mx-auto max-w-[760px]">
            <Composer
              ref={composerRef}
              value={draft}
              onChange={setDraft}
              onSubmit={send}
              onStop={() => activeTurn && cancel(activeTurn.id)}
              busy={busy}
              blocked={sources.length === 0}
              optionsOpen={optionsOpen}
              optionsActive={optionsActive}
              onToggleOptions={() => setOptionsOpen((v) => !v)}
              optionsPanel={optionsPanel}
            />
            <p className="mt-2 text-center text-[12px] text-text-tertiary">
              Answers come from this repository&rsquo;s indexed code and can be wrong — check the cited sources. Each question is answered independently.
            </p>
          </div>
        </div>
      </div>

      {showRail && (
        <aside aria-label="Sources for the selected answer" className="cs-scrollbar hidden h-full min-h-0 overflow-y-auto border-l border-border-subtle bg-surface-1 px-5 pb-10 pt-6 xl:block">
          {rail}
        </aside>
      )}
      {!isDesktop && (
        <Modal open={drawerOpen} onOpenChange={setDrawerOpen} title="Sources" side="right">
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
