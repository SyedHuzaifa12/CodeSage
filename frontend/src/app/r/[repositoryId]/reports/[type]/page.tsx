"use client";

import { useEffect, useMemo, useState } from "react";
import { BookOpen, ChevronDown, RefreshCw } from "lucide-react";
import { useRepositoryContext } from "@/context/RepositoryContext";
import { TopologyMark } from "@/components/devices/TopologyMark";
import { DiagramFrame } from "@/components/domain/DiagramFrame";
import { ReportSectionView } from "@/components/domain/ReportSectionView";
import { Button } from "@/components/ui/Button";
import { ErrorPanel, Notice, StaleBanner } from "@/components/state/StateVocabulary";
import { ApiError } from "@/lib/api/client";
import { useGenerateReport, useReport, useReportsList } from "@/lib/query/reports";
import { useIntelligence } from "@/lib/query/workspace";
import { AI_SECTION_HEADINGS, REPORT_DESCRIPTIONS, groupReportHistory, isAiSection } from "@/lib/reportFormat";
import { REPORT_TYPES, REPORT_TYPE_TITLES, type ReportResponse, type ReportType } from "@/lib/types/reports";
import { cn, formatRelativeTime } from "@/lib/utils";

function formatStamp(iso: string | null): string {
  if (!iso) return "—";
  return `${new Date(iso).toISOString().replace("T", " ").slice(0, 16)} UTC`;
}

function generationLine(r: ReportResponse): string {
  const gm = r.generation_metadata as Record<string, unknown>;
  const ms = typeof gm.generation_ms === "number" ? `${gm.generation_ms.toLocaleString("en-US")} ms` : null;
  const ai = gm.ai_used
    ? `${String(gm.ai_provider ?? "")} / ${String(gm.ai_model ?? "")}`
    : gm.ai_synthesis_failed
      ? "AI synthesis failed — deterministic sections only"
      : gm.ai_synthesis_skipped
        ? "AI synthesis disabled by configuration"
        : "deterministic only";
  return [`generated ${formatRelativeTime(r.generated_at)}`, ms, ai].filter(Boolean).join(" · ");
}

export default function ReportReaderPage({ params }: { params: { type: string } }) {
  const { repositoryId } = useRepositoryContext();
  const type = params.type as ReportType;
  const valid = (REPORT_TYPES as readonly string[]).includes(type);
  const report = useReport(repositoryId, valid ? type : undefined);
  const history = useReportsList(repositoryId, false);
  const intelligence = useIntelligence(repositoryId);
  const generate = useGenerateReport();
  const [historyOpen, setHistoryOpen] = useState(false);
  const [viewId, setViewId] = useState<string | null>(null);
  const [current, setCurrent] = useState(0);

  const group = useMemo(() => (valid ? groupReportHistory(history.data?.reports ?? [])[type] : undefined), [history.data, type, valid]);
  const latest = report.data;
  const viewing = viewId ? group?.history.find((r) => r.id === viewId && r.status === "ready") ?? latest : latest;
  const isHistorical = Boolean(viewing && latest && viewing.id !== latest.id);
  const notFound = report.isError && report.error instanceof ApiError && report.error.status === 404;
  const aiHeading = valid ? AI_SECTION_HEADINGS[type] : null;
  const lastResult = generate.data && generate.data.report_type === type ? generate.data : null;
  const latestFailed = lastResult?.status === "failed" ? lastResult : group?.latestFailed ?? null;
  const cycles = intelligence.data?.circular_dependencies ?? [];

  useEffect(() => {
    setViewId(null);
    setHistoryOpen(false);
  }, [type]);

  // Reading rail tracks the section in view inside the app's scrolling <main>.
  useEffect(() => {
    const root = document.querySelector("main");
    const sections = [...document.querySelectorAll<HTMLElement>("[data-report-section]")];
    if (!root || sections.length === 0) return;
    const io = new IntersectionObserver(
      (entries) => {
        const top = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (top) setCurrent(Number((top.target as HTMLElement).dataset.reportSection));
      },
      { root, rootMargin: "-10% 0px -70% 0px" },
    );
    sections.forEach((s) => io.observe(s));
    return () => io.disconnect();
  }, [viewing?.id]);

  if (!valid) {
    return (
      <div className="px-11 py-16">
        <p className="text-text-secondary">&ldquo;{params.type}&rdquo; isn&rsquo;t a report type.</p>
      </div>
    );
  }

  const run = (force: boolean) => generate.mutate({ id: repositoryId, type, force }, { onSuccess: () => setViewId(null) });
  const title = REPORT_TYPE_TITLES[type];
  const aiIndex = viewing ? viewing.sections.findIndex((s) => isAiSection(s, type)) : -1;
  const diagrams = viewing?.diagrams.map((d) => <DiagramFrame key={d.title} title={d.title} mermaidCode={d.mermaid_code} diagramType={d.diagram_type} />);

  return (
    <div className="cs-page">
      <div className="mx-auto grid max-w-[1080px] grid-cols-1 gap-14 px-5 pb-28 pt-10 sm:px-11 lg:grid-cols-[minmax(0,1fr)_150px]">
        <div className="min-w-0 max-w-[710px]">
          {latestFailed && (
            <Notice
              tone="bad"
              className="mb-6"
              title={`The latest generation failed${latest ? " — the previous ready report is shown below" : ""}`}
              actions={
                <Button size="sm" variant="secondary" onClick={() => run(true)} loading={generate.isPending}>
                  Retry
                </Button>
              }
            >
              <div className="cs-errmono">{latestFailed.error_message ?? "Report generation failed."}</div>
            </Notice>
          )}

          {generate.isPending && (
            <div aria-busy="true">
              <div className="flex items-center gap-3">
                <p className="cs-mono-label">{title}</p>
                <span className="cs-chip border-[var(--cs-violet-line)] bg-[var(--cs-violet-tint)] text-violet" role="status">
                  <span className="cs-chip-dot cs-pulse" aria-hidden="true" />
                  generating…
                </span>
              </div>
              <div className="cs-skel mt-4 h-10 w-[55%]" />
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="cs-skel mt-6 h-[90px]" style={{ opacity: 1 - i * 0.18 }} />
              ))}
              <p className="mt-6 text-small text-text-tertiary">
                Generation runs inside the request{aiHeading ? " and includes one AI synthesis call" : ""}. The rest of CodeSage stays usable.
              </p>
            </div>
          )}

          {!generate.isPending && report.isLoading && (
            <div>
              <div className="cs-skel h-3 w-48" />
              <div className="cs-skel mt-4 h-10 w-3/5" />
              {[0, 1, 2].map((i) => (
                <div key={i} className="cs-skel mt-6 h-[80px]" />
              ))}
            </div>
          )}

          {!generate.isPending && report.isError && !notFound && <ErrorPanel error={report.error} onRetry={() => report.refetch()} />}
          {!generate.isPending && generate.isError && <ErrorPanel className="mb-6" error={generate.error} onRetry={() => run(Boolean(latest))} />}

          {!generate.isPending && notFound && (
            <div className="flex min-h-[52vh] flex-col items-start justify-center gap-4 py-10">
              <TopologyMark variant="mark" size={40} />
              <p className="cs-mono-label">{title}</p>
              <h1 className="cs-display">No {title} has been generated yet.</h1>
              <p className="max-w-[58ch] text-text-secondary">{REPORT_DESCRIPTIONS[type]}</p>
              <p className="max-w-[58ch] text-small text-text-tertiary">
                {aiHeading
                  ? `Deterministic sections come straight from the index; one AI-written section (“${aiHeading}”) is citation-checked before it's shown. Usually 1–2.5 s.`
                  : "Every section is computed from the index — no AI involved. Usually well under a second."}
              </p>
              <Button variant="primary" onClick={() => run(false)} className="mt-1">
                <BookOpen size={15} aria-hidden="true" />
                Generate this report
              </Button>
            </div>
          )}

          {!generate.isPending && viewing && viewing.status === "ready" && (
            <>
              <header>
                <p className="cs-mono-label">
                  {viewing.title ?? title} ·{" "}
                  <span className="normal-case tracking-normal" title="repository_version — the corpus fingerprint this report was generated against">
                    {viewing.repository_version ?? "unindexed"}
                  </span>
                </p>
                <div className="mt-2.5 flex flex-wrap items-start justify-between gap-4">
                  <h1 className="font-display text-[clamp(34px,4.2vw,46px)] italic leading-[1.05] tracking-[-0.022em] text-text-primary">{viewing.title ?? title}</h1>
                  <span className="flex flex-shrink-0 items-center gap-3 pt-2">
                    {viewing.stale && !isHistorical && (
                      <span className="cs-chip border-warning/35 text-warning">
                        <span className="cs-chip-dot" aria-hidden="true" />
                        stale
                      </span>
                    )}
                    <button className="cs-link" onClick={() => run(true)} disabled={generate.isPending}>
                      <RefreshCw size={13} aria-hidden="true" /> regenerate
                    </button>
                  </span>
                </div>
                {/* When synthesis succeeds the backend swaps the deterministic summary for the LLM's
                    (reports/service.py) — and that summary is not citation-checked, so say so. */}
                {viewing.summary &&
                  (viewing.generation_metadata?.ai_used === true ? (
                    <div className="cs-voice mt-4 py-1 pr-2">
                      <p className="cs-lede !text-[18px]">{viewing.summary}</p>
                      <p className="mt-1.5 flex items-center gap-2 text-small text-text-tertiary">
                        <span className="cs-tag text-violet">AI</span> summary written by the model; not citation-checked
                      </p>
                    </div>
                  ) : (
                    <p className="cs-lede mt-4 !text-[18px]">{viewing.summary}</p>
                  ))}
                <p className="cs-monoline mt-3">{generationLine(viewing)}</p>
                <div className="mt-2.5 flex flex-wrap items-center gap-4">
                  <button className="cs-disclosure-btn" onClick={() => setHistoryOpen((v) => !v)} aria-expanded={historyOpen}>
                    view history · {group?.history.length ?? 1} <ChevronDown size={12} aria-hidden="true" />
                  </button>
                </div>
                {historyOpen && group && (
                  <div className="cs-fade-in mt-2">
                    {group.history.map((r) => {
                      const isCurrent = latest?.id === r.id;
                      const isViewing = viewing.id === r.id;
                      return (
                        <div key={r.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-t border-border-subtle py-2 font-mono text-[11.5px] text-text-secondary">
                          <span className="min-w-0 truncate">
                            {formatStamp(r.generated_at ?? r.created_at)} · {r.repository_version ?? ""}
                          </span>
                          {r.status === "failed" ? (
                            <span className="text-danger" title={r.error_message ?? undefined}>failed</span>
                          ) : isViewing ? (
                            <span className="text-violet">{isCurrent ? "current · viewing" : "viewing"}</span>
                          ) : (
                            <button className="cs-link" onClick={() => setViewId(isCurrent ? null : r.id)}>
                              {isCurrent ? "current" : "view"}
                            </button>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </header>

              {isHistorical && (
                <Notice
                  tone="info"
                  className="mt-6"
                  title="Viewing a previous generation"
                  actions={
                    <Button size="sm" variant="secondary" onClick={() => setViewId(null)}>
                      Back to latest
                    </Button>
                  }
                >
                  Generated {formatRelativeTime(viewing.generated_at)} against an earlier version of the index.
                </Notice>
              )}
              {viewing.stale && !isHistorical && (
                <StaleBanner
                  className="mt-6"
                  message="Findings below may be outdated. Every re-index changes the corpus version, even when no files changed."
                  onRegenerate={() => run(true)}
                  regenerating={generate.isPending}
                />
              )}
              {Boolean((viewing.generation_metadata as Record<string, unknown>).ai_synthesis_failed) && (
                <Notice tone="info" className="mt-6" title="AI narrative unavailable">
                  Showing deterministic sections only.
                  {typeof (viewing.generation_metadata as Record<string, unknown>).ai_synthesis_failure_reason === "string" && (
                    <div className="cs-errmono">{String((viewing.generation_metadata as Record<string, unknown>).ai_synthesis_failure_reason)}</div>
                  )}
                </Notice>
              )}

              <div className="mt-8">
                {viewing.sections.map((s, i) => (
                  <div key={`${s.heading}-${i}`} data-report-section={i}>
                    <ReportSectionView section={s} id={`section-${i}`} index={i} ai={isAiSection(s, type)} cycles={cycles}>
                      {i === aiIndex && type === "architecture" && diagrams}
                    </ReportSectionView>
                  </div>
                ))}
                {aiIndex < 0 && viewing.diagrams.length > 0 && (
                  <section className="border-t border-border-subtle pt-[30px]">
                    <h2 className="font-sans text-[18px] font-semibold text-text-primary">Diagrams</h2>
                    {diagrams}
                  </section>
                )}
              </div>
            </>
          )}
        </div>

        {!generate.isPending && viewing && viewing.status === "ready" && viewing.sections.length > 0 && (
          <nav aria-label="Report sections" className="sticky top-20 hidden self-start lg:block">
            <p className="cs-mono-label">Reading</p>
            <div className="mt-3">
              {viewing.sections.map((s, i) => (
                <button
                  key={`${s.heading}-${i}`}
                  onClick={() => document.getElementById(`section-${i}`)?.scrollIntoView({ behavior: "smooth", block: "start" })}
                  className={cn(
                    "block w-full border-l py-1.5 pl-3 text-left text-[12px] leading-snug transition-colors",
                    current === i ? "border-l-2 border-violet pl-[11px] text-text-primary" : "border-border-subtle text-text-tertiary hover:text-text-primary",
                  )}
                  aria-current={current === i ? "true" : undefined}
                >
                  {s.heading}
                </button>
              ))}
            </div>
          </nav>
        )}
      </div>
    </div>
  );
}
