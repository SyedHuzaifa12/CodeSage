"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMemo } from "react";
import { RequireReady } from "@/components/nav/RequireReady";
import { useRepositoryContext } from "@/context/RepositoryContext";
import { useReportsList } from "@/lib/query/reports";
import { groupReportHistory } from "@/lib/reportFormat";
import { REPORT_TYPES, REPORT_TYPE_TITLES } from "@/lib/types/reports";
import { cn } from "@/lib/utils";

const DOT: Record<string, { cls: string; label: string }> = {
  ready: { cls: "border-success bg-success", label: "ready" },
  stale: { cls: "border-warning bg-warning", label: "stale" },
  failed: { cls: "border-danger bg-danger", label: "last generation failed" },
  none: { cls: "border-text-tertiary", label: "not generated" },
};

/** Department-style report tabs (Design System §16) with each type's real status from GET /reports?latest_only=false. */
function ReportTabs() {
  const { repositoryId } = useRepositoryContext();
  const pathname = usePathname();
  const history = useReportsList(repositoryId, false);
  const grouped = useMemo(() => groupReportHistory(history.data?.reports ?? []), [history.data]);
  return (
    <div className="cs-glass sticky top-0 z-10 flex gap-7 overflow-x-auto border-b border-border-subtle px-5 [scrollbar-width:none] sm:px-11" role="tablist" aria-label="Report types">
      {REPORT_TYPES.map((type) => {
        const href = `/r/${repositoryId}/reports/${type}`;
        const active = pathname === href;
        const g = grouped[type];
        const state = !g ? "none" : g.latestFailed ? "failed" : g.ready?.stale ? "stale" : g.ready ? "ready" : "none";
        return (
          <Link
            key={type}
            href={href}
            role="tab"
            aria-selected={active}
            className={cn(
              "relative flex items-center gap-2 whitespace-nowrap pb-[15px] pt-[18px] font-mono text-[11px] font-medium uppercase tracking-[0.07em] transition-colors",
              active ? "text-text-primary after:absolute after:inset-x-0 after:-bottom-px after:h-[2px] after:bg-violet" : "text-text-tertiary hover:text-text-primary",
            )}
          >
            <span className={cn("h-1.5 w-1.5 rounded-full border", DOT[state].cls)} aria-hidden="true" />
            {REPORT_TYPE_TITLES[type]}
            <span className="sr-only">({DOT[state].label})</span>
          </Link>
        );
      })}
    </div>
  );
}

export default function ReportsLayout({ children }: { children: React.ReactNode }) {
  return (
    <RequireReady>
      <ReportTabs />
      {children}
    </RequireReady>
  );
}
