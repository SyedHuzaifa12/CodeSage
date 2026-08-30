"use client";

import { useState } from "react";
import { useRepositoryContext } from "@/context/RepositoryContext";
import { DiagramFrame } from "@/components/domain/DiagramFrame";
import { ReportSectionView } from "@/components/domain/ReportSectionView";
import { SkeletonBlock } from "@/components/state/Loading";
import { EmptyState, ErrorPanel, StaleBanner } from "@/components/state/StateVocabulary";
import { useGenerateReport, useReport } from "@/lib/query/reports";
import { REPORT_TYPES, REPORT_TYPE_TITLES, type ReportType } from "@/lib/types/reports";
import { ApiError } from "@/lib/api/client";
import { formatRelativeTime } from "@/lib/utils";

export default function ReportReaderPage({ params }: { params: { type: string } }) {
  const { repositoryId } = useRepositoryContext();
  const type = params.type as ReportType;
  const isValidType = (REPORT_TYPES as readonly string[]).includes(type);
  const [activeSection, setActiveSection] = useState<string | null>(null);

  const report = useReport(repositoryId, isValidType ? type : undefined);
  const generate = useGenerateReport();

  if (!isValidType) {
    return <div className="p-11"><EmptyState message={`Unknown report type "${type}".`} /></div>;
  }

  const notFound = report.isError && report.error instanceof ApiError && report.error.status === 404;

  return (
    <div className="flex gap-8 px-11 pb-10">
      <div className="max-w-[780px] flex-1 pt-6">
        {report.isLoading && <SkeletonBlock />}

        {notFound && (
          <EmptyState
            message={`No ${REPORT_TYPE_TITLES[type]} has been generated yet.`}
            action={{ label: "Generate this report", onClick: () => generate.mutate({ id: repositoryId, type }) }}
          />
        )}

        {report.isError && !notFound && (
          <ErrorPanel message={report.error instanceof ApiError ? report.error.message : "Couldn't load this report."} />
        )}

        {report.data && report.data.status === "failed" && (
          <ErrorPanel
            message={report.data.error_message ?? "Report generation failed."}
            onRetry={() => generate.mutate({ id: repositoryId, type, force: true })}
          />
        )}

        {report.data && (report.data.status === "pending" || report.data.status === "generating") && (
          <div className="flex flex-col gap-3">
            <span className="w-fit font-mono text-[10px] text-text-tertiary">generating…</span>
            <SkeletonBlock />
            <SkeletonBlock />
          </div>
        )}

        {report.data && report.data.status === "ready" && (
          <>
            <div className="cs-mono-label">
              {REPORT_TYPE_TITLES[type].toUpperCase()} &middot; {report.data.repository_version ?? "—"}
            </div>
            <div className="mt-2 flex items-start justify-between gap-4">
              <h1 className="max-w-[520px] font-display text-display italic text-text-primary">
                {report.data.title ?? REPORT_TYPE_TITLES[type]}
              </h1>
              <div className="flex flex-shrink-0 items-center gap-2.5 pt-1.5">
                {report.data.stale && <span className="font-mono text-[10px] text-warning">&#9679; stale</span>}
                <button
                  onClick={() => generate.mutate({ id: repositoryId, type, force: true })}
                  disabled={generate.isPending}
                  className="font-mono text-[10.5px] text-violet hover:underline disabled:opacity-50"
                >
                  regenerate
                </button>
              </div>
            </div>
            {report.data.summary && <p className="mt-3 text-body text-text-secondary">{report.data.summary}</p>}
            <div className="mt-3 font-mono text-[10px] text-text-tertiary">
              generated {formatRelativeTime(report.data.generated_at)}
            </div>

            {report.data.stale && (
              <StaleBanner
                className="mt-4"
                message="The repository has changed since generation — findings below may be outdated."
                onRegenerate={() => generate.mutate({ id: repositoryId, type, force: true })}
                regenerating={generate.isPending}
              />
            )}

            <div className="mt-6 flex flex-col gap-6">
              {report.data.sections.map((section, i) => (
                <div key={i} onFocus={() => setActiveSection(section.heading)}>
                  <ReportSectionView section={section} id={`section-${i}`} />
                </div>
              ))}
            </div>

            {report.data.diagrams.length > 0 && (
              <div className="mt-8 flex flex-col gap-8">
                {report.data.diagrams.map((diagram, i) => (
                  <DiagramFrame
                    key={i}
                    title={diagram.title}
                    mermaidCode={diagram.mermaid_code}
                    footnote={`derived from ${String(report.data!.generation_metadata.relationship_count ?? "N")} relationships`}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {report.data?.status === "ready" && report.data.sections.length > 0 && (
        <nav aria-label="Report sections" className="hidden w-[130px] flex-shrink-0 pt-16 lg:block">
          <div className="cs-mono-label mb-2.5">READING</div>
          {report.data.sections.map((section, i) => (
            <a
              key={i}
              href={`#section-${i}`}
              className="block border-l-[1.5px] py-1 pl-2.5 font-mono text-[10.5px]"
              style={{
                borderColor: activeSection === section.heading ? "var(--cs-accent-violet)" : "transparent",
                color: activeSection === section.heading ? "var(--cs-accent-violet)" : "var(--cs-text-tertiary)",
              }}
            >
              {section.heading}
            </a>
          ))}
        </nav>
      )}
    </div>
  );
}
