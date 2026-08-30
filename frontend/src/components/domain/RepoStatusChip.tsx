import type { IndexingStatus, RepositoryStatus } from "@/lib/types/repository";
import { cn } from "@/lib/utils";

const LABELS: Record<string, string> = {
  pending: "Queued",
  cloning: "Cloning",
  ready: "Ready to index",
  failed: "Failed",
  deleted: "Deleted",
  not_started: "Not indexed",
  indexing: "Indexing",
  indexed: "Indexed",
};

function colorFor(status: RepositoryStatus, indexingStatus: IndexingStatus): string {
  if (status === "failed" || indexingStatus === "failed") return "var(--cs-danger)";
  if (indexingStatus === "indexed") return "var(--cs-success)";
  if (status === "cloning" || indexingStatus === "indexing") return "var(--cs-accent-violet)";
  return "var(--cs-text-tertiary)";
}

/** Repo status chip (Design System §9.4 / §4's onboarding status table). */
export function RepoStatusChip({
  status,
  indexingStatus,
  className,
}: {
  status: RepositoryStatus;
  indexingStatus: IndexingStatus;
  className?: string;
}) {
  const label =
    status === "failed" || indexingStatus === "failed"
      ? "Failed"
      : indexingStatus === "indexed"
        ? "Indexed"
        : status === "ready"
          ? indexingStatus === "indexing"
            ? "Indexing"
            : "Ready to index"
          : LABELS[status] ?? status;
  const color = colorFor(status, indexingStatus);
  const pulsing = status === "pending" || status === "cloning" || indexingStatus === "indexing";

  return (
    <span
      className={cn("inline-flex items-center gap-1.5 font-mono text-[10.5px]", className)}
      style={{ color }}
    >
      <span
        className={cn("h-[5px] w-[5px] rounded-full", pulsing && "animate-pulse")}
        style={{ background: color }}
        aria-hidden="true"
      />
      {label.toUpperCase()}
    </span>
  );
}
