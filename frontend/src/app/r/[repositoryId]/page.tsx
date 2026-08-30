"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { useRepositoryContext } from "@/context/RepositoryContext";
import { OnboardingNarrative } from "@/components/domain/OnboardingNarrative";
import { TopologyDiagram } from "@/components/domain/TopologyDiagram";
import { TopologyMark } from "@/components/devices/TopologyMark";
import { InlineStat, HeroStat } from "@/components/domain/StatTile";
import { Input } from "@/components/ui/Input";
import { SkeletonBlock } from "@/components/state/Loading";
import { ErrorPanel } from "@/components/state/StateVocabulary";
import { useDependencyGraph, useIntelligence, useWorkspace } from "@/lib/query/workspace";
import { formatNumber } from "@/lib/utils";
import { ApiError } from "@/lib/api/client";

export default function OverviewPage() {
  const { repository, isReady } = useRepositoryContext();
  const router = useRouter();
  const [question, setQuestion] = useState("");

  const workspace = useWorkspace(repository?.id, { poll: !isReady });
  const intelligence = useIntelligence(repository?.id, { enabled: isReady });
  const depGraph = useDependencyGraph(repository?.id, { enabled: isReady });

  if (!repository) return <SkeletonBlock className="m-11" />;

  if (!isReady) return <OnboardingNarrative repository={repository} />;

  const langs = Object.keys(workspace.data?.language_distribution ?? {}).slice(0, 3);
  const hotspotCount = intelligence.data?.dependency_hotspots.length ?? 0;
  const hotspotFiles = new Set((intelligence.data?.dependency_hotspots ?? []).map((h) => h.module_path));

  function goAsk(e: FormEvent) {
    e.preventDefault();
    if (!question.trim() || !repository) return;
    router.push(`/r/${repository.id}/ask?q=${encodeURIComponent(question.trim())}`);
  }

  return (
    <div className="relative min-h-full overflow-hidden">
      <TopologyMark variant="watermark" />
      <div className="relative z-10 grid min-h-[calc(100vh-56px)] grid-cols-1 gap-2 px-11 pb-8 pt-1.5 lg:grid-cols-[0.85fr_1.35fr]">
        <div className="flex flex-col gap-6 pt-3.5">
          <div>
            <div className="cs-mono-label mb-3">REPOSITORY INTELLIGENCE</div>
            <h1 className="font-display text-masthead-lg italic leading-none text-text-primary">{repository.name}</h1>
            {repository.github_url && (
              <div className="mt-3 font-mono text-[11px] text-text-tertiary">{repository.github_url}</div>
            )}
          </div>

          {intelligence.isLoading && <SkeletonBlock />}
          {intelligence.isError && (
            <ErrorPanel message={intelligence.error instanceof ApiError ? intelligence.error.message : "Couldn't load intelligence."} />
          )}
          {intelligence.data && (
            <p className="max-w-[420px] font-display text-lede text-text-secondary">
              {formatNumber(workspace.data?.total_files)} files and {formatNumber(intelligence.data.total_symbols)}{" "}
              symbols &mdash;{" "}
              <span className="text-[oklch(0.88_0.11_300)]">
                {hotspotCount} module{hotspotCount === 1 ? "" : "s"}
              </span>{" "}
              cross the dependency-hotspot threshold.
            </p>
          )}

          <div className="flex gap-7 border-y border-border-subtle py-4">
            <InlineStat label="FILES" value={formatNumber(workspace.data?.total_files)} />
            <InlineStat label="SYMBOLS" value={formatNumber(intelligence.data?.total_symbols)} />
            <InlineStat label="LANGUAGES" value={langs.join(" · ") || "—"} />
          </div>

          {hotspotCount > 0 && (
            <HeroStat
              label="DEPENDENCY HOTSPOTS"
              value={String(hotspotCount)}
              caption={`${intelligence.data?.dependency_hotspots[0]?.module_path ?? ""} carries the most incoming dependencies`}
              progressFraction={hotspotCount / Math.max(workspace.data?.total_files ?? hotspotCount, 1)}
            />
          )}

          <form onSubmit={goAsk} className="flex flex-col gap-2 border-t border-border-subtle pt-5">
            <div className="cs-mono-label">ASK CODESAGE</div>
            <Input
              editorial
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask about this repository…"
              aria-label="Ask CodeSage"
            />
            <Link href={`/r/${repository.id}/ask`} className="w-fit font-mono text-[10px] text-violet hover:underline">
              continue in Ask &rarr;
            </Link>
          </form>
        </div>

        <div className="flex min-h-[420px] flex-col">
          <div className="flex items-baseline justify-between pb-1.5">
            <div className="cs-mono-label">REPOSITORY TOPOLOGY</div>
            <Link href={`/r/${repository.id}/graph`} className="font-mono text-[10px] text-text-tertiary hover:text-violet">
              open in Graph &rarr;
            </Link>
          </div>
          <div className="flex-1">
            {depGraph.isLoading && <SkeletonBlock className="h-full" />}
            {depGraph.data && (
              <TopologyDiagram
                nodes={depGraph.data.nodes}
                edges={depGraph.data.edges}
                hotspotCount={hotspotCount}
                hotspotFiles={hotspotFiles}
              />
            )}
          </div>
          <div className="flex items-center gap-4 pt-1.5 font-mono text-[10px] text-text-tertiary">
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-px w-3.5 bg-[oklch(0.42_0.02_280)]" /> observed dependency
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-2 w-2 rounded-full border-[1.5px] border-violet" /> hotspot
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
