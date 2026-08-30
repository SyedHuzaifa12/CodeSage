"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { TopologyMark } from "@/components/devices/TopologyMark";
import { useRepositoryContext } from "@/context/RepositoryContext";

/**
 * Gates Ask/Search/Graph/Reports (Design System §1): a repository with
 * status != ready or indexing_status != indexed cannot be navigated into
 * these pages — only Overview/Explorer remain reachable in reduced form.
 */
export function RequireReady({ children }: { children: ReactNode }) {
  const { repositoryId, isReady, isLoading } = useRepositoryContext();

  if (isLoading) return null;

  if (!isReady) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 text-center">
        <TopologyMark variant="mark" size={32} />
        <p className="max-w-[360px] text-small text-text-secondary">
          This page unlocks once indexing finishes. Watch progress on Overview.
        </p>
        <Link href={`/r/${repositoryId}`} className="font-mono text-[11px] text-violet hover:underline">
          Back to Overview &rarr;
        </Link>
      </div>
    );
  }

  return <>{children}</>;
}
