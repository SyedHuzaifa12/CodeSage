"use client";

import Link from "next/link";
import { Search } from "lucide-react";
import { TopologyMark } from "@/components/devices/TopologyMark";
import { RepoStatusChip } from "@/components/domain/RepoStatusChip";
import type { Repository } from "@/lib/types/repository";
import { formatRelativeTime } from "@/lib/utils";

/** Utility strip / top bar (ported from Main.dc.html / Ask.dc.html's 56px header row). */
export function TopBar({ repository }: { repository: Repository | undefined }) {
  return (
    <header className="relative z-10 flex h-14 flex-shrink-0 items-center gap-3.5 px-11">
      <Link href="/" className="flex items-center gap-3.5" aria-label="CodeSage — all repositories">
        <TopologyMark variant="mark" size={24} title="CodeSage" />
        <span className="cs-mono-label tracking-[0.12em] text-[10.5px] text-[oklch(0.46_0.01_280)]">CODESAGE</span>
      </Link>
      <div className="flex-1" />
      {repository && (
        <>
          {repository.indexing_status === "indexed" ? (
            <span className="hidden items-center gap-1.5 font-mono text-[10.5px] text-success sm:flex">
              <span className="h-[5px] w-[5px] rounded-full bg-success" aria-hidden="true" />
              INDEXED &middot; {formatRelativeTime(repository.updated_at).toUpperCase()}
            </span>
          ) : (
            <RepoStatusChip status={repository.status} indexingStatus={repository.indexing_status} className="hidden sm:flex" />
          )}
          <span className="hidden font-display text-[15px] italic text-[oklch(0.65_0.01_280)] md:inline">
            {repository.name}
          </span>
        </>
      )}
      <Search size={15} strokeWidth={1.6} className="text-[oklch(0.55_0.01_280)]" aria-hidden="true" />
      <span className="h-[26px] w-[26px] rounded-full bg-surface-2" aria-hidden="true" />
    </header>
  );
}
