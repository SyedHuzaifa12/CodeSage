"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { RequireReady } from "@/components/nav/RequireReady";
import { useRepositoryContext } from "@/context/RepositoryContext";
import { REPORT_TYPES, REPORT_TYPE_TITLES } from "@/lib/types/reports";
import { cn } from "@/lib/utils";

function ReportTabs() {
  const { repositoryId } = useRepositoryContext();
  const pathname = usePathname();

  return (
    <div className="flex gap-6 border-b border-border-subtle px-11 pt-6">
      {REPORT_TYPES.map((type) => {
        const href = `/r/${repositoryId}/reports/${type}`;
        const active = pathname === href;
        return (
          <Link
            key={type}
            href={href}
            className={cn(
              "-mb-px border-b-[1.5px] pb-4 font-mono text-[11px]",
              active ? "border-violet text-text-primary" : "border-transparent text-text-tertiary hover:text-text-secondary",
            )}
          >
            {REPORT_TYPE_TITLES[type]}
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
