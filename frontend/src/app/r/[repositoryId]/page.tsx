"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState, useSyncExternalStore, type FormEvent } from "react";
import { ArrowRight, RotateCcw, Send } from "lucide-react";
import { useRepositoryContext } from "@/context/RepositoryContext";
import { OnboardingNarrative } from "@/components/domain/OnboardingNarrative";
import { TopologyDiagram } from "@/components/domain/TopologyDiagram";
import { TopologyMark } from "@/components/devices/TopologyMark";
import { GraphLegend as Legend } from "@/components/domain/GraphLegend";
import { ConfidenceRing } from "@/components/devices/ConfidenceRing";
import { ErrorPanel, Notice } from "@/components/state/StateVocabulary";
import { askSession } from "@/lib/askSession";
import { fileToModule } from "@/lib/graphModel";
import { useKnowledgeState } from "@/lib/query/knowledge";
import { useDependencyGraph, useIntelligence, useWorkspace } from "@/lib/query/workspace";
import { formatNumber } from "@/lib/utils";

const PARSED_LANGUAGES = new Set(["Python", "JavaScript", "TypeScript", "Java"]);

export default function OverviewPage() {
  const { repository, isReady } = useRepositoryContext();
  if (!repository) return <OverviewSkeleton />;
  if (!isReady) return <OnboardingNarrative repository={repository} />;
  return <Overview repositoryId={repository.id} />;
}

function OverviewSkeleton() {
  return (
    <div className="mx-auto grid max-w-[1200px] grid-cols-1 gap-14 px-5 py-11 sm:px-11 xl:grid-cols-[0.85fr_1.35fr]">
      <div className="flex flex-col gap-4">
        <div className="cs-skel h-3 w-40" />
        <div className="cs-skel h-14 w-3/4" />
        <div className="cs-skel h-5 w-full" />
        <div className="cs-skel h-5 w-2/3" />
        <div className="cs-skel mt-6 h-40" />
      </div>
      <div className="cs-skel aspect-[1.08]" />
    </div>
  );
}

function Overview({ repositoryId }: { repositoryId: string }) {
  const router = useRouter();
  const { repository } = useRepositoryContext();
  const workspace = useWorkspace(repositoryId);
  const intelligence = useIntelligence(repositoryId);
  const depGraph = useDependencyGraph(repositoryId);
  const knowledge = useKnowledgeState(repositoryId);
  const turns = useSyncExternalStore(askSession.subscribe, () => askSession.get(repositoryId), () => askSession.get(repositoryId));
  const [question, setQuestion] = useState("");

  const I = intelligence.data;
  const W = workspace.data;
  const hotspots = useMemo(() => I?.dependency_hotspots ?? [], [I]);
  const top = hotspots[0];
  const hotSet = useMemo(() => new Set(hotspots.slice(0, 5).map((h) => h.module_path)), [hotspots]);
  const orphanSet = useMemo(() => new Set((I?.orphan_files ?? []).map(fileToModule)), [I]);
  const langs = Object.entries(W?.language_distribution ?? {}).sort((a, b) => b[1] - a[1]);
  const parsedFiles = langs.filter(([l]) => PARSED_LANGUAGES.has(l)).reduce((a, [, n]) => a + n, 0);
  const lastAnswered = [...turns].reverse().find((t) => t.response);
  const maxModule = Math.max(1, ...(I?.largest_modules ?? []).map((m) => m.symbol_count));
  const moduleCount = depGraph.data?.nodes.length ?? 0;

  const suggestions = useMemo(() => {
    const out = ["Explain the architecture of this repository"];
    if (I?.largest_modules[0]) out.push(`What would be affected if I change ${I.largest_modules[0].path}?`);
    out.push("Where are the tests?");
    return out;
  }, [I]);

  function go(q: string) {
    const t = q.trim();
    if (!t) return;
    router.push(`/r/${repositoryId}/ask?q=${encodeURIComponent(t)}`);
  }
  function onSubmit(e: FormEvent) {
    e.preventDefault();
    go(question);
  }

  if (intelligence.isLoading || workspace.isLoading) return <OverviewSkeleton />;

  return (
    <div className="cs-page cs-page-glow">
      <TopologyMark variant="watermark" />
      <div className="relative z-10 mx-auto max-w-[1200px] px-5 pb-24 pt-10 sm:px-11">
        <div className="grid grid-cols-1 items-start gap-12 xl:grid-cols-[minmax(0,0.85fr)_minmax(0,1.35fr)] xl:gap-14">
          <div className="min-w-0">
            <p className="cs-mono-label">Repository intelligence</p>
            <h1 className="cs-masthead mt-2 !text-[clamp(38px,5vw,58px)]">{repository?.name}</h1>
            {repository?.github_url && <p className="cs-monoline mt-2">{repository.github_url}</p>}
            <nav aria-label="More sections" className="mt-4 flex flex-wrap gap-2 md:hidden">
              <Link className="cs-chipbtn" href={`/r/${repositoryId}/explorer`}>explorer</Link>
              <Link className="cs-chipbtn" href={`/r/${repositoryId}/graph`}>graph</Link>
              <Link className="cs-chipbtn" href={`/r/${repositoryId}/settings`}>settings</Link>
            </nav>

            {repository?.error_message && (
              <Notice tone="warn" className="mt-5" title="Partially indexed">
                {repository.error_message}
              </Notice>
            )}
            {intelligence.isError && <ErrorPanel className="mt-5" error={intelligence.error} onRetry={() => intelligence.refetch()} />}
            {I && I.status === "failed" && (
              <Notice tone="warn" className="mt-5" title="Repository intelligence failed">
                {I.error_message ?? "The analysis step failed; symbols and the knowledge index may still be usable."}
              </Notice>
            )}

            {I && W && (
              <p className="cs-lede mt-6">
                <b>{formatNumber(W.total_files)} files</b> and <b>{formatNumber(I.total_symbols)} symbols</b> —{" "}
                {hotspots.length ? (
                  <>
                    <b>{hotspots.length} modules</b> carry the most incoming dependencies
                    {I.circular_dependencies.length ? <>, and <b>{I.circular_dependencies.length}</b> circular dependency chains were detected.</> : "."}
                  </>
                ) : (
                  "no internal dependencies were resolved."
                )}
              </p>
            )}

            <div className="cs-statstrip mt-6">
              <div>
                <span className="cs-mono-label">Files</span>
                <span className="cs-statval">{formatNumber(W?.total_files)}</span>
              </div>
              <div>
                <span className="cs-mono-label">Symbols</span>
                <span className="cs-statval">{formatNumber(I?.total_symbols)}</span>
              </div>
              <div className="min-w-0">
                <span className="cs-mono-label">Languages</span>
                <span className="cs-statval !text-[13px]">{langs.slice(0, 3).map(([l]) => l).join(" · ") || "—"}</span>
              </div>
            </div>

            {top && (
              <div className="cs-callout mt-6 px-5 py-[18px]">
                <p className="cs-mono-label">Dependency hotspots</p>
                <div className="mt-2 flex items-end gap-3.5">
                  <span className="font-display text-[72px] italic leading-none tracking-[-0.04em] text-text-primary">{hotspots.length}</span>
                  <span className="pb-2 text-small text-text-secondary">of {formatNumber(moduleCount)} modules</span>
                </div>
                <p className="mt-2 text-small text-text-secondary">
                  <Link className="font-mono text-violet hover:underline" href={`/r/${repositoryId}/graph?focus=${encodeURIComponent(top.module_path)}`}>
                    {top.module_path}
                  </Link>{" "}
                  carries the most incoming dependencies ({top.incoming_dependencies}).
                </p>
                <div
                  className="mt-4 flex h-[58px] items-end gap-[5px]"
                  role="img"
                  aria-label={`Incoming dependencies across the top ${hotspots.length} hotspots: ${hotspots.map((h) => `${h.module_path} ${h.incoming_dependencies}`).join(", ")}`}
                >
                  {hotspots.map((h, i) => (
                    <Link
                      key={h.module_path}
                      href={`/r/${repositoryId}/graph?focus=${encodeURIComponent(h.module_path)}`}
                      title={`${h.module_path} · ${h.incoming_dependencies} dependents`}
                      aria-label={`${h.module_path}, ${h.incoming_dependencies} dependents`}
                      className="group flex h-full flex-1 items-end rounded-[3px]"
                    >
                      <i
                        className="block w-full rounded-t-[2px] transition-colors group-hover:bg-[var(--cs-accent-violet-hover)]"
                        style={{
                          height: `${Math.max(6, (h.incoming_dependencies / top.incoming_dependencies) * 100)}%`,
                          background: i === 0 ? "linear-gradient(180deg, oklch(0.85 0.1 300), var(--cs-accent-violet))" : "oklch(0.75 0.13 300 / 0.28)",
                          transformOrigin: "bottom",
                          animation: `cs-grow-y 700ms var(--cs-ease-out) ${i * 45}ms both`,
                        }}
                      />
                    </Link>
                  ))}
                </div>
                <div className="mt-2 flex justify-between cs-monoline !text-[11px]">
                  <span>incoming dependencies · top {hotspots.length}</span>
                  <span>
                    {top.incoming_dependencies} → {hotspots[hotspots.length - 1].incoming_dependencies}
                  </span>
                </div>
              </div>
            )}

            <form onSubmit={onSubmit} className="mt-8">
              <label className="cs-mono-label" htmlFor="ov-ask">
                Ask CodeSage
              </label>
              <div className="mt-1 flex items-center gap-2.5">
                <input
                  id="ov-ask"
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder="Ask about this repository…"
                  autoComplete="off"
                  className="cs-underline-input h-12 font-display text-[19px] italic"
                />
                <button
                  type="submit"
                  aria-label="Ask"
                  disabled={!question.trim()}
                  className="grid h-10 w-10 flex-none place-items-center rounded-full bg-[linear-gradient(180deg,oklch(0.82_0.12_300),oklch(0.72_0.135_300))] text-[oklch(0.18_0.03_300)] shadow-[inset_0_1px_0_oklch(1_0_0/0.35)] transition-transform active:scale-95 disabled:opacity-30"
                >
                  <Send size={16} aria-hidden="true" />
                </button>
              </div>
              {lastAnswered?.response ? (
                <div className="mt-4 border-t border-border-subtle pt-3.5">
                  <p className="cs-mono-label">Last in this session</p>
                  <Link href={`/r/${repositoryId}/ask`} className="mt-1 block font-display text-[15.5px] italic text-text-primary hover:text-[var(--cs-accent-violet-hover)]">
                    &ldquo;{lastAnswered.question}&rdquo;
                  </Link>
                  <div className="mt-2">
                    <ConfidenceRing value={lastAnswered.response.verification.status} withLabel />
                  </div>
                </div>
              ) : (
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  <span className="cs-mono-label">Try</span>
                  {suggestions.map((s) => (
                    <button key={s} type="button" className="cs-qchip" onClick={() => go(s)}>
                      {s}
                    </button>
                  ))}
                </div>
              )}
              <Link href={`/r/${repositoryId}/ask`} className="cs-link mt-4">
                continue in Ask <ArrowRight size={13} aria-hidden="true" />
              </Link>
            </form>
          </div>

          <div className="min-w-0">
            <div className="flex items-baseline justify-between">
              <p className="cs-mono-label">Repository topology</p>
              <Link href={`/r/${repositoryId}/graph`} className="cs-link">
                open in Graph <ArrowRight size={13} aria-hidden="true" />
              </Link>
            </div>
            <div className="mt-1.5">
              {depGraph.isLoading && <div className="cs-skel aspect-[1.08]" />}
              {depGraph.isError && <ErrorPanel error={depGraph.error} onRetry={() => depGraph.refetch()} />}
              {depGraph.data && (
                <TopologyDiagram
                  nodes={depGraph.data.nodes}
                  edges={depGraph.data.edges}
                  hotspots={hotSet}
                  cycles={depGraph.data.circular_dependencies}
                  orphans={orphanSet}
                  layoutKey={`overview-${repositoryId}`}
                  onNodeClick={(n) => router.push(`/r/${repositoryId}/graph?focus=${encodeURIComponent(n)}`)}
                />
              )}
            </div>
            <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
              <Legend cycles={(I?.circular_dependencies.length ?? 0) > 0} />
              {depGraph.data && (
                <span className="cs-monoline !text-[11px]">
                  top {Math.min(24, depGraph.data.nodes.length)} of {formatNumber(depGraph.data.nodes.length)} modules
                </span>
              )}
            </div>
          </div>
        </div>

        {I && W && (
          <section aria-label="How CodeSage built its understanding" className="mt-16 border-t border-border-subtle pt-[18px]">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="cs-mono-label">From files to grounded answers</p>
              <span className="cs-monoline !text-[11px]">every figure below is read from the index</span>
            </div>
            <div className="relative mt-5 grid grid-cols-2 gap-y-7 md:grid-cols-3 xl:grid-cols-6 xl:before:absolute xl:before:left-1.5 xl:before:right-1.5 xl:before:top-1.5 xl:before:h-px xl:before:bg-[linear-gradient(90deg,var(--cs-border-strong),var(--cs-border-strong)_70%,var(--cs-accent-violet))]">
              <Station href={`/r/${repositoryId}/explorer`} label="Scanned" value={formatNumber(W.total_files)} detail={`files · ${W.ignored_files} ignored`} />
              <Station href={`/r/${repositoryId}/explorer`} label="Parsed" value={formatNumber(parsedFiles)} detail="files in Py / JS / TS / Java" />
              <Station
                href={`/r/${repositoryId}/explorer`}
                label="Symbols"
                value={formatNumber(I.total_symbols)}
                detail={`${I.total_classes} classes · ${I.total_functions} functions · ${I.total_methods} methods`}
              />
              <Station
                href={`/r/${repositoryId}/graph?mode=call`}
                label="Relationships"
                value={formatNumber(I.total_imports + I.total_calls + I.inheritance_count)}
                detail={`${I.total_imports} imports · ${I.total_calls} calls · ${I.inheritance_count} inheritance`}
              />
              <Station
                href={`/r/${repositoryId}/graph`}
                label="Module graph"
                value={formatNumber(I.dependency_count)}
                detail={`edges · ${I.circular_dependencies.length} cycles · ${I.orphan_files.length} orphans`}
              />
              <Station
                href={`/r/${repositoryId}/ask`}
                label="Knowledge"
                value={knowledge.data ? formatNumber(knowledge.data.total_chunks) : "—"}
                detail={`chunks · ${knowledge.data?.embedding_model_version ?? "local embeddings"} → Ask`}
                last
              />
            </div>
          </section>
        )}

        {I && (
          <div className="mt-14 grid grid-cols-1 gap-11 md:grid-cols-2 xl:grid-cols-3">
            <section>
              <p className="cs-mono-label">Largest modules</p>
              <div className="mt-3">
                {I.largest_modules.slice(0, 6).map((m) => (
                  <Link
                    key={m.path}
                    href={`/r/${repositoryId}/explorer?file=${encodeURIComponent(m.path)}`}
                    className="grid grid-cols-[minmax(0,1fr)_34px] items-center gap-x-2.5 gap-y-1.5 border-t border-border-subtle py-2.5 font-mono text-[12px] text-text-secondary transition-colors hover:text-text-primary"
                  >
                    <span className="truncate">{m.path}</span>
                    <b className="text-right font-medium text-text-primary">{m.symbol_count}</b>
                    <span className="cs-bar col-span-2 !h-[2px]">
                      <i style={{ width: `${(m.symbol_count / maxModule) * 100}%` }} />
                    </span>
                  </Link>
                ))}
              </div>
            </section>
            <section>
              <p className="cs-mono-label">Circular dependencies · {I.circular_dependencies.length}</p>
              <div className="mt-3">
                {I.circular_dependencies.length === 0 && (
                  <p className="border-t border-border-subtle py-2.5 font-mono text-[12px] text-text-secondary">No cycles in the resolved dependency graph.</p>
                )}
                {I.circular_dependencies.slice(0, 8).map((c) => (
                  <Link
                    key={c.join(">")}
                    href={`/r/${repositoryId}/graph?focus=${encodeURIComponent(c[0])}`}
                    className="flex items-start gap-2 border-t border-border-subtle py-2.5 font-mono text-[12px] text-text-secondary transition-colors hover:text-text-primary"
                  >
                    <RotateCcw size={12} className="mt-1 flex-none text-danger" aria-hidden="true" />
                    <span className="break-words">{[...c, c[0]].join(" → ")}</span>
                  </Link>
                ))}
              </div>
            </section>
            <section>
              <p className="cs-mono-label">Architecture observations</p>
              <div className="mt-3">
                {I.architecture_hints.map((h) => (
                  <p key={h} className="border-t border-border-subtle py-2.5 font-mono text-[12px] text-text-secondary">
                    {h}
                  </p>
                ))}
                <p className="border-t border-border-subtle py-2.5 font-mono text-[12px] text-text-tertiary">
                  entry points {I.entry_points.length} · orphan files {I.orphan_files.length}
                </p>
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}

function Station({ href, label, value, detail, last }: { href: string; label: string; value: string; detail: string; last?: boolean }) {
  return (
    <Link href={href} className="group relative block rounded-md pr-3.5">
      <span
        className={
          last
            ? "relative z-10 block h-[13px] w-[13px] rounded-full border-[1.5px] border-violet bg-violet shadow-[0_0_0_4px_var(--cs-bg),0_0_12px_oklch(0.75_0.13_300/0.6)]"
            : "relative z-10 block h-[13px] w-[13px] rounded-full border-[1.5px] border-text-tertiary bg-bg shadow-[0_0_0_4px_var(--cs-bg)] transition-colors group-hover:border-violet"
        }
        aria-hidden="true"
      />
      <span className="cs-mono-label mt-3.5 block">{label}</span>
      <span className="my-2 block font-display text-[36px] italic leading-none tracking-[-0.02em] text-text-primary transition-colors group-hover:text-[var(--cs-accent-violet-hover)]">
        {value}
      </span>
      <span className="block font-mono text-[11px] leading-snug text-text-tertiary">{detail}</span>
    </Link>
  );
}
