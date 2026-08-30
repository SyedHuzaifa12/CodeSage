"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useRepositoryContext } from "@/context/RepositoryContext";
import { RequireReady } from "@/components/nav/RequireReady";
import { Input } from "@/components/ui/Input";
import { SearchResultRow } from "@/components/domain/SearchResultRow";
import { SkeletonBlock } from "@/components/state/Loading";
import { ErrorPanel, NoResultsState, PartialNotice } from "@/components/state/StateVocabulary";
import { useRetrievalQuery } from "@/lib/query/retrieval";
import { ApiError } from "@/lib/api/client";

function SearchInner() {
  const { repositoryId } = useRepositoryContext();
  const router = useRouter();
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");

  const retrieval = useRetrievalQuery(repositoryId, query);
  const sourcesConfirmedBy = new Map<string, number>();
  retrieval.data?.results.forEach((r) => {
    if (r.sources.length > 1) sourcesConfirmedBy.set("dual", (sourcesConfirmedBy.get("dual") ?? 0) + 1);
  });

  return (
    <div className="flex gap-11 px-11 py-8">
      <div className="flex max-w-[780px] flex-1 flex-col gap-5">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setQuery(draft);
          }}
        >
          <div className="cs-mono-label mb-1.5">{query ? "INVESTIGATING" : "SEARCH"}</div>
          <Input
            editorial
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="password hashing, rate limiting, JWT verification…"
            aria-label="Search this repository"
            className="text-[28px]"
          />
        </form>

        {retrieval.data && retrieval.data.stats.sources_failed.length > 0 && (
          <PartialNotice
            message={`${retrieval.data.stats.sources_failed.join(", ")} unavailable — showing ${retrieval.data.sources_requested.filter((s) => !retrieval.data!.stats.sources_failed.includes(s)).join(" + ")} results`}
          />
        )}

        <div className="flex flex-col">
          {retrieval.isLoading && (
            <div className="flex flex-col gap-4 pt-4">
              <SkeletonBlock />
              <SkeletonBlock />
            </div>
          )}
          {retrieval.isError && (
            <ErrorPanel message={retrieval.error instanceof ApiError ? retrieval.error.message : "Search failed."} />
          )}
          {retrieval.data && retrieval.data.results.length === 0 && <NoResultsState query={query} />}
          {retrieval.data?.results.map((result) => (
            <SearchResultRow
              key={`${result.file_path}-${result.start_line}-${result.rank}`}
              result={result}
              onAsk={() => router.push(`/r/${repositoryId}/ask?q=${encodeURIComponent(query)}`)}
            />
          ))}
        </div>
      </div>

      {retrieval.data && retrieval.data.results.length > 0 && (
        <div className="w-[220px] flex-shrink-0 pt-16 lg:block hidden">
          <div className="cs-mono-label mb-3.5">RETRIEVAL SCOPE</div>
          <svg width={180} height={110} viewBox="0 0 180 110" role="img" aria-label="Retrieval source overlap">
            <circle cx={72} cy={55} r={46} fill="oklch(0.75 0.13 300 / 0.1)" stroke="oklch(0.75 0.13 300 / 0.5)" />
            <circle cx={118} cy={55} r={38} fill="oklch(0.75 0.12 200 / 0.1)" stroke="oklch(0.65 0.09 200 / 0.5)" />
            <text x={30} y={30} fontFamily="var(--font-plex-mono)" fontSize={9.5} fill="oklch(0.8 0.11 300)">semantic</text>
            <text x={128} y={30} fontFamily="var(--font-plex-mono)" fontSize={9.5} fill="oklch(0.72 0.09 200)">lexical</text>
            <text x={86} y={60} fontFamily="var(--font-plex-mono)" fontSize={9.5} fill="oklch(0.85 0.006 280)">
              {sourcesConfirmedBy.get("dual") ?? 0}
            </text>
          </svg>
          <div className="mt-1.5 font-mono text-[10px] text-text-tertiary">
            {retrieval.data.results.length} results &middot; {sourcesConfirmedBy.get("dual") ?? 0} dual-confirmed
          </div>
        </div>
      )}
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
