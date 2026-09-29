"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Info, Search } from "lucide-react";
import { TopologyMark } from "@/components/devices/TopologyMark";
import { RepoStatusChip } from "@/components/domain/RepoStatusChip";
import { CommandPalette } from "@/components/nav/CommandPalette";
import { RepoSwitcher } from "@/components/nav/RepoSwitcher";
import type { Repository } from "@/lib/types/repository";

/** Glass top bar: identity, ⌘K palette trigger, index status, repository switcher. */
export function TopBar({ repository }: { repository?: Repository }) {
  const [paletteOpen, setPaletteOpen] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <header className="cs-glass relative z-20 flex h-14 flex-shrink-0 items-center gap-2 px-3 after:pointer-events-none after:absolute after:inset-x-0 after:-bottom-px after:h-px after:bg-[linear-gradient(90deg,var(--cs-border-subtle),var(--cs-border-strong)_35%,var(--cs-border-strong)_65%,var(--cs-border-subtle))] sm:gap-3.5 sm:px-5">
      <Link href="/" className="group flex items-center gap-2.5 rounded-md px-1 py-1" aria-label="CodeSage — all repositories">
        <span className="transition-transform duration-panel ease-cs group-hover:-rotate-6">
          <TopologyMark variant="mark" size={24} />
        </span>
        <span className="hidden font-mono text-[11.5px] font-medium tracking-[0.2em] text-text-primary sm:inline">CODESAGE</span>
      </Link>
      <div className="flex-1" />
      <button
        onClick={() => setPaletteOpen(true)}
        aria-label="Open command palette"
        className="flex h-[34px] items-center gap-2.5 rounded-[8px] px-2 text-[12.5px] text-text-tertiary transition-colors hover:text-text-secondary md:min-w-[230px] md:border md:border-border-subtle md:px-3 md:hover:border-border-strong"
      >
        <Search size={15} aria-hidden="true" />
        <span className="hidden md:inline">Jump to a file, symbol or page</span>
        <kbd className="ml-auto hidden rounded border border-border-strong px-1.5 py-0.5 font-mono text-[10px] text-text-tertiary md:inline">
          ⌘K
        </kbd>
      </button>
      {repository && (
        <>
          <span className="hidden lg:inline-flex">
            <RepoStatusChip
              status={repository.status}
              indexingStatus={repository.indexing_status}
              updatedAt={repository.updated_at}
            />
          </span>
          <RepoSwitcher repository={repository} />
        </>
      )}
      <Link
        href="/about"
        aria-label="How CodeSage works"
        title="How CodeSage works"
        className="hidden h-9 w-9 place-items-center rounded-[8px] text-text-secondary transition-colors hover:bg-surface-2 hover:text-text-primary sm:grid"
      >
        <Info size={17} strokeWidth={1.5} aria-hidden="true" />
      </Link>
      <span
        className="hidden h-7 w-7 place-items-center rounded-full border border-border-subtle bg-surface-3 font-mono text-[10px] text-text-secondary sm:grid"
        title="Single local workspace — CodeSage has no accounts"
        aria-label="Local workspace, no account"
        role="img"
      >
        LW
      </span>
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} repository={repository} />
    </header>
  );
}
