"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { ArrowRight, ChevronDown, Search as SearchIcon } from "lucide-react";
import { useRepositoryContext } from "@/context/RepositoryContext";
import { RequireReady } from "@/components/nav/RequireReady";
import { SourcePill } from "@/components/ask/EvidenceRail";
import { Button } from "@/components/ui/Button";
import { ErrorPanel, NoResultsState, Notice } from "@/components/state/StateVocabulary";
import { useRetrievalQuery } from "@/lib/query/retrieval";
import type { EvidenceResult, RetrievalQueryData } from "@/lib/types/retrieval";
import { cn } from "@/lib/utils";

const SOURCES = ["semantic", "lexical", "structural"] as const;
const SOURCE_COLOR: Record<string, string> = {
  semantic: "var(--cs-accent-violet)",
  lexical: "var(--cs-accent-cyan)",
  structural: "var(--cs-warning)",
};
const STAGE_COLOR: Record<string, string> = {
  cache_lookup: "var(--cs-text-tertiary)",
  retrieval_parallel: "var(--cs-accent-violet)",
  structural: "var(--cs-warning)",
  fusion: "var(--cs-accent-cyan)",
  symbol_enrichment: "var(--cs-info)",
  reranking: "var(--cs-text-secondary)",
};
const EXAMPLES = ["authentication", "configuration", "database session", "error handling", "tests"];

const regionKey = (r: EvidenceResult) => [...r.sources].sort().join("+");

/** Three-source overlap computed from each result's real `sources` array. Regions are filters. */
function SourceVenn({ results, active, onSelect }: { results: EvidenceResult[]; active: string | null; onSelect: (k: string | null) => void }) {
  const counts = new Map<string, number>();
  for (const r of results) counts.set(regionKey(r), (counts.get(regionKey(r)) ?? 0) + 1);
  const circles: [string, number, number][] = [
    ["semantic", 88, 78],
    ["lexical", 152, 78],
    ["structural", 120, 132],
  ];
  const regions: [string, number, number][] = [
    ["semantic", 68, 66],
    ["lexical", 172, 66],
    ["structural", 120, 158],
    ["lexical+semantic", 120, 60],
    ["semantic+structural", 94, 118],
    ["lexical+structural", 146, 118],
    ["lexical+semantic+structural", 120, 98],
  ];
  return (
    <svg viewBox="0 0 240 200" className="mt-2 block h-auto w-full overflow-visible" role="group" aria-label="Retrieval source overlap">
      {circles.map(([s, x, y]) => (
        <circle key={s} cx={x} cy={y} r={50} fill={SOURCE_COLOR[s]} fillOpacity={0.1} stroke={SOURCE_COLOR[s]} strokeOpacity={0.55} />
      ))}
      {circles.map(([s, x, y], i) => (
        <text key={`${s}-l`} x={i === 2 ? x : i === 0 ? x - 40 : x + 40} y={i === 2 ? y + 64 : y - 56} textAnchor="middle" fontFamily="var(--font-plex-mono)" fontSize={9.5} fill={SOURCE_COLOR[s]}>
          {s}
        </text>
      ))}
      {regions.map(([k, x, y]) => {
        const n = counts.get(k) ?? 0;
        return (
          <g
            key={k}
            role="button"
            tabIndex={n ? 0 : -1}
            aria-pressed={active === k}
            aria-label={`${n} results found by ${k.replace(/\+/g, " and ")}${n ? ". Filter to these" : ""}`}
            onClick={() => n && onSelect(active === k ? null : k)}
            onKeyDown={(e) => {
              if ((e.key === "Enter" || e.key === " ") && n) {
                e.preventDefault();
                onSelect(active === k ? null : k);
              }
            }}
            style={{ cursor: n ? "pointer" : "default", outline: "none" }}
          >
            <circle cx={x} cy={y - 4} r={13} fill={active === k ? "var(--cs-accent-violet)" : "transparent"} fillOpacity={0.25} />
            <text x={x} y={y} textAnchor="middle" fontFamily="var(--font-plex-mono)" fontSize={12.5} fontWeight={500} fill={n ? "var(--cs-text-primary)" : "var(--cs-text-tertiary)"}>
              {n}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function ResultRow({ r, query, repositoryId }: { r: EvidenceResult; query: string; repositoryId: string }) {
  const [open, setOpen] = useState(false);
  const loc = `${r.file_path}${r.start_line ? `:${r.start_line}${r.end_line && r.end_line !== r.start_line ? `–${r.end_line}` : ""}` : ""}`;
  return (
    <div className="cs-hover-row -mx-1.5 grid grid-cols-[26px_minmax(0,1fr)] items-start gap-3.5 px-3 py-4 md:grid-cols-[28px_minmax(0,1fr)_auto]" data-active={open}>
      <span className="font-display text-[21px] italic leading-none tracking-[-0.02em] text-text-tertiary">{String(r.rank).padStart(2, "0")}</span>
      <div className="min-w-0">
        <Link
          href={`/r/${repositoryId}/explorer?file=${encodeURIComponent(r.file_path)}${r.start_line ? `&line=${r.start_line}` : ""}`}
          className="break-all font-mono text-[13px] font-medium text-text-primary hover:text-[var(--cs-accent-violet-hover)]"
        >
          {loc}
        </Link>
        {r.symbol_name && (
          <div className="mt-0.5 break-all font-mono text-[12px] text-violet">
            <span className="mr-1.5 text-text-tertiary">{r.symbol_type}</span>
            {r.qualified_name ?? r.symbol_name}
          </div>
        )}
        <div className="mt-2.5 flex flex-wrap gap-x-2.5 gap-y-0.5">
          <button onClick={() => setOpen((v) => !v)} aria-expanded={open} className="cs-disclosure-btn">
            why this matched <ChevronDown size={12} aria-hidden="true" />
          </button>
          <Link href={`/r/${repositoryId}/ask?q=${encodeURIComponent(query)}`} className="cs-link">
            Ask <ArrowRight size={13} aria-hidden="true" />
          </Link>
        </div>
        {open && (
          <div className="cs-panel cs-fade-in mt-3 px-3.5 py-3">
            <ul className="cs-reasons">
              {r.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
            <div className="mt-2.5 grid grid-cols-[78px_minmax(0,1fr)_36px] items-center gap-x-2.5 gap-y-1.5 font-mono text-[11px]">
              {r.source_scores.map((s) => (
                <SourceScoreRow key={s.source} label={s.source} score={s.score} color={SOURCE_COLOR[s.source] ?? "var(--cs-text-secondary)"} />
              ))}
              {r.rerank_score != null && <SourceScoreRow label="rerank" score={r.rerank_score} color="var(--cs-text-secondary)" />}
            </div>
          </div>
        )}
      </div>
      <div className="col-start-2 flex flex-row flex-wrap items-center gap-2 md:col-start-auto md:flex-col md:items-end">
        <div className="flex flex-wrap justify-end gap-1">
          {r.sources.map((s) => (
            <SourcePill key={s} source={s} />
          ))}
        </div>
        <span className="cs-tabular font-mono text-[17px] font-medium tracking-[-0.01em]">{r.final_score.toFixed(2)}</span>
        <span className="cs-bar block !h-[3px] w-24" aria-hidden="true">
          <i style={{ width: `${Math.min(100, r.final_score * 100)}%` }} />
        </span>
      </div>
    </div>
  );
}

function SourceScoreRow({ label, score, color }: { label: string; score: number; color: string }) {
  return (
    <>
      <span style={{ color }}>{label}</span>
      <span className="h-1 overflow-hidden rounded bg-surface-3">
        <i className="block h-full" style={{ width: `${Math.min(100, score * 100)}%`, background: color }} />
      </span>
      <span className="text-text-secondary">{score.toFixed(2)}</span>
    </>
  );
}

function ScopeRail({ data, venn, onVenn }: { data: RetrievalQueryData; venn: string | null; onVenn: (k: string | null) => void }) {
  const st = data.stats;
  const dual = data.results.filter((r) => r.sources.length > 1).length;
  const max = Math.max(1, st.candidates_semantic, st.candidates_lexical, st.candidates_structural, st.candidates_after_dedup);
  const stages = Object.entries(st.stage_latency_ms);
  const total = stages.reduce((a, [, v]) => a + v, 0) || 1;
  return (
    <div>
      <p className="cs-mono-label">Retrieval scope</p>
      <SourceVenn results={data.results} active={venn} onSelect={onVenn} />
      <p className="cs-monoline text-center !text-[11px]">
        {data.results.length} results · {dual} confirmed by more than one source
      </p>
      <p className="mt-1 text-center text-[11.5px] text-text-tertiary">Select a region to filter</p>
      <p className="cs-mono-label mt-8">Candidates</p>
      <div className="mt-3 grid gap-1.5">
        {[
          ["semantic", st.candidates_semantic, SOURCE_COLOR.semantic],
          ["lexical", st.candidates_lexical, SOURCE_COLOR.lexical],
          ["structural", st.candidates_structural, SOURCE_COLOR.structural],
          ["after dedup", st.candidates_after_dedup, "var(--cs-text-secondary)"],
        ].map(([label, v, c]) => (
          <div key={label as string} className="grid grid-cols-[82px_minmax(0,1fr)_30px] items-center gap-2.5 font-mono text-[11px] text-text-tertiary">
            <span>{label}</span>
            <span className="h-[5px] overflow-hidden rounded bg-surface-3">
              <i className="block h-full rounded" style={{ width: `${((v as number) / max) * 100}%`, background: c as string, transformOrigin: "left", animation: "cs-grow 700ms var(--cs-ease-out) both" }} />
            </span>
            <b className="text-right font-medium text-text-primary">{v as number}</b>
          </div>
        ))}
      </div>
      <p className="cs-mono-label mt-8">
        Latency · {st.total_latency_ms.toLocaleString("en-US")} ms{st.cache_hit ? " · cache hit" : ""}
      </p>
      <div className="mb-2 mt-3 flex h-2.5 gap-px overflow-hidden rounded-[5px] bg-surface-3" aria-hidden="true">
        {stages.map(([k, v]) => (
          <i key={k} className="h-full min-w-[2px]" style={{ flex: Math.max(v, total * 0.01), background: STAGE_COLOR[k] ?? "var(--cs-text-tertiary)" }} title={`${k} ${v}ms`} />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-3.5 gap-y-1 font-mono text-[10.5px] text-text-tertiary">
        {stages.map(([k, v]) => (
          <span key={k}>
            <i className="cs-legend-dot" style={{ background: STAGE_COLOR[k] ?? "var(--cs-text-tertiary)" }} aria-hidden="true" />
            {k.replace(/_/g, " ")} {v}ms
          </span>
        ))}
      </div>
    </div>
  );
}

function SearchInner() {
  const { repositoryId } = useRepositoryContext();
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const urlQuery = searchParams.get("q") ?? "";
  const [draft, setDraft] = useState(urlQuery);
  const [sources, setSources] = useState<string[]>([...SOURCES]);
  const [topK, setTopK] = useState(10);
  const [rerank, setRerank] = useState(false);
  const [venn, setVenn] = useState<string | null>(null);

  useEffect(() => setDraft(urlQuery), [urlQuery]);
  useEffect(() => setVenn(null), [urlQuery, sources, topK, rerank]);

  const retrieval = useRetrievalQuery(repositoryId, urlQuery, {
    sources: sources.length < SOURCES.length ? sources : undefined,
    topK,
    rerank: rerank || undefined,
    enabled: sources.length > 0,
  });
  const data = retrieval.data && retrieval.data.query === urlQuery ? retrieval.data : undefined;
  const results = useMemo(() => (data ? (venn ? data.results.filter((r) => regionKey(r) === venn) : data.results) : []), [data, venn]);

  function run(q: string) {
    const t = q.trim();
    if (!t) return;
    router.replace(`${pathname}?q=${encodeURIComponent(t)}`);
  }

  const failed = data?.stats.sources_failed ?? [];
  return (
    <div className="cs-page">
      <div className="mx-auto grid max-w-[1200px] grid-cols-1 gap-8 px-5 pb-24 pt-10 sm:px-11 lg:grid-cols-[minmax(0,1fr)_260px] lg:gap-[52px]">
        <div className="min-w-0">
          <p className="cs-mono-label">{urlQuery ? "Investigating" : "Search"}</p>
          <form
            onSubmit={(e: FormEvent) => {
              e.preventDefault();
              run(draft);
            }}
            role="search"
            className="cs-underline-input mt-2 flex items-center gap-3.5 focus-within:[background-size:100%_2px,100%_1px]"
          >
            <SearchIcon size={20} className="flex-none text-text-tertiary" aria-hidden="true" />
            <label htmlFor="search-input" className="sr-only">
              Search this repository
            </label>
            <input
              id="search-input"
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="password hashing, rate limiting, JWT verification…"
              autoComplete="off"
              spellCheck={false}
              className="h-16 min-w-0 flex-1 bg-transparent font-display text-[clamp(22px,2.6vw,28px)] italic text-text-primary !outline-none placeholder:text-text-tertiary"
            />
            <Button type="submit" variant="primary" size="sm" disabled={!draft.trim()}>
              Investigate
            </Button>
          </form>
          <div className="mt-3.5 flex flex-wrap items-center gap-x-[18px] gap-y-2.5">
            <span className="flex flex-wrap gap-1.5" role="group" aria-label="Retrieval sources">
              {SOURCES.map((s) => (
                <button
                  key={s}
                  className="cs-chipbtn"
                  aria-pressed={sources.includes(s)}
                  onClick={() => setSources((cur) => (cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]))}
                >
                  <span className="h-1.5 w-1.5 rounded-full" style={{ background: SOURCE_COLOR[s] }} aria-hidden="true" />
                  {s}
                </button>
              ))}
            </span>
            <label className="flex items-center gap-1.5 text-small text-text-secondary">
              top-K
              <select className="cs-select" value={topK} onChange={(e) => setTopK(Number(e.target.value))}>
                {[5, 10, 20, 50].map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex cursor-pointer items-center gap-2 text-small text-text-secondary" title="Cross-encoder reranking — about 1.5 s per query">
              <input type="checkbox" checked={rerank} onChange={(e) => setRerank(e.target.checked)} className="accent-[var(--cs-accent-violet)]" />
              deep rerank <span className="text-text-tertiary">slower, more precise</span>
            </label>
          </div>
          {sources.length === 0 && <Notice tone="warn" className="mt-4">Select at least one retrieval source.</Notice>}

          <div className="mt-6" aria-live="polite" aria-busy={retrieval.isFetching}>
            {!urlQuery && (
              <div>
                <p className="max-w-[62ch] text-text-secondary">
                  Search runs hybrid retrieval without the LLM: three sources, fused deterministically and ranked, each result carrying the reasons it
                  matched.
                </p>
                <div className="cs-rows mt-6">
                  {[
                    ["semantic", "Embedding similarity over code chunks — finds code by meaning."],
                    ["lexical", "Trigram match on symbol names, qualified names and file paths — not raw code text."],
                    ["structural", "One-hop expansion over the knowledge graph from the other sources' hits."],
                  ].map(([s, t]) => (
                    <div key={s} className="flex items-start gap-3 py-3">
                      <span className="w-[86px] flex-none">
                        <SourcePill source={s} />
                      </span>
                      <span className="text-small text-text-secondary">{t}</span>
                    </div>
                  ))}
                </div>
                <p className="cs-mono-label mt-8">Try</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {EXAMPLES.map((x) => (
                    <button key={x} className="cs-qchip" onClick={() => run(x)}>
                      {x}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {urlQuery && retrieval.isLoading && (
              <div className="flex flex-col gap-3 pt-2">
                {[0, 1, 2, 3, 4].map((i) => (
                  <div key={i} className="cs-skel h-[58px]" style={{ opacity: 1 - i * 0.16 }} />
                ))}
              </div>
            )}
            {urlQuery && retrieval.isError && <ErrorPanel error={retrieval.error} onRetry={() => retrieval.refetch()} />}
            {data && failed.length > 0 && (
              <Notice tone="info" className="mb-4">
                {failed.join(", ")} unavailable — showing {data.sources_requested.filter((s) => !failed.includes(s)).join(" + ") || "remaining"} results
              </Notice>
            )}
            {data && data.results.length === 0 && (
              <NoResultsState
                query={data.query}
                hint="Lexical search matches symbol names and file paths, not raw code text — try a symbol or file name. Semantic matches below a similarity of 0.5 are dropped."
              />
            )}
            {data && data.results.length > 0 && (
              <>
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className="cs-monoline">
                    {data.results.length} results for &ldquo;{data.query}&rdquo; · {data.stats.total_latency_ms.toLocaleString("en-US")} ms ·{" "}
                    {data.stats.candidates_after_dedup} candidates
                    {data.stats.cache_hit ? " · cached" : ""}
                    {data.stats.reranking_applied ? " · reranked" : ""}
                    {retrieval.isFetching ? " · refreshing…" : ""}
                  </p>
                  {venn && (
                    <button className="cs-link" onClick={() => setVenn(null)}>
                      clear overlap filter ({venn})
                    </button>
                  )}
                </div>
                <div className={cn("cs-rows mt-3 transition-opacity", retrieval.isFetching && "opacity-60")}>
                  {results.map((r) => (
                    <ResultRow key={`${r.rank}-${r.file_path}-${r.start_line}`} r={r} query={data.query} repositoryId={repositoryId} />
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
        <aside aria-label="Retrieval scope" className="min-w-0 lg:pt-4">
          {data && data.results.length > 0 ? (
            <ScopeRail data={data} venn={venn} onVenn={setVenn} />
          ) : (
            <div className="hidden lg:block">
              <p className="cs-mono-label">Retrieval scope</p>
              <p className="mt-2 text-small text-text-tertiary">Run a query to see how the three sources overlap and where time was spent.</p>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

export default function SearchPage() {
  return (
    <RequireReady>
      <SearchInner />
    </RequireReady>
  );
}
