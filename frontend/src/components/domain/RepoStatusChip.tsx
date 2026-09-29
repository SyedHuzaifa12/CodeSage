import type { IndexingStatus, RepositoryStatus } from "@/lib/types/repository";
import { cn, formatRelativeTime } from "@/lib/utils";

/**
 * Repo status chip — the ONE place repository/indexing status maps to a UI
 * label (Design System §4 / prototype spec §4.2–4.3). Never re-derived per page.
 */
export function repoStatusLabel(status: RepositoryStatus, indexingStatus: IndexingStatus): string {
  if (status === "failed") return "Failed";
  if (status === "pending") return "Queued";
  if (status === "cloning") return "Cloning";
  if (indexingStatus === "indexing") return "Indexing";
  if (indexingStatus === "failed") return "Index failed";
  if (indexingStatus === "indexed") return "Indexed";
  return "Ready to index";
}

export function RepoStatusChip({
  status,
  indexingStatus,
  updatedAt,
  className,
}: {
  status: RepositoryStatus;
  indexingStatus: IndexingStatus;
  /** When provided on an indexed repository, appends "· 2h ago". */
  updatedAt?: string;
  className?: string;
}) {
  const label = repoStatusLabel(status, indexingStatus);
  const failed = status === "failed" || indexingStatus === "failed";
  const indexed = !failed && indexingStatus === "indexed";
  const active = !failed && (status === "cloning" || indexingStatus === "indexing");
  const tone = failed
    ? "text-danger border-danger/40 bg-danger/10"
    : indexed
      ? "text-success border-success/35 bg-success/[0.06]"
      : active
        ? "text-violet border-[var(--cs-violet-line)] bg-[var(--cs-violet-tint)]"
        : "";
  return (
    <span className={cn("cs-chip", tone, className)} role={active ? "status" : undefined}>
      <span
        className={cn("cs-chip-dot", active && "cs-pulse", !failed && !indexed && !active && "bg-text-tertiary")}
        aria-hidden="true"
      />
      {label}
      {indexed && updatedAt ? ` · ${formatRelativeTime(updatedAt)}` : ""}
    </span>
  );
}
