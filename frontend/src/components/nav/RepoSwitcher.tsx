"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ArrowRight, ChevronDown } from "lucide-react";
import { RepoStatusChip } from "@/components/domain/RepoStatusChip";
import { useRepositories } from "@/lib/query/repositories";
import type { Repository } from "@/lib/types/repository";

/** Top-bar repository switcher: a keyboard-navigable menu over GET /repositories. */
export function RepoSwitcher({ repository }: { repository: Repository }) {
  const [open, setOpen] = useState(false);
  const { data } = useRepositories();
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    requestAnimationFrame(() => menuRef.current?.querySelector<HTMLElement>("[role=menuitem]")?.focus());
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  function onMenuKey(e: React.KeyboardEvent) {
    const items = [...(menuRef.current?.querySelectorAll<HTMLElement>("[role=menuitem]") ?? [])];
    const i = items.indexOf(document.activeElement as HTMLElement);
    if (e.key === "ArrowDown") {
      e.preventDefault();
      items[(i + 1) % items.length]?.focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      items[(i - 1 + items.length) % items.length]?.focus();
    } else if (e.key === "Escape") {
      setOpen(false);
      buttonRef.current?.focus();
    }
  }

  const repos = data?.repositories ?? [repository];
  return (
    <div className="relative" ref={rootRef}>
      <button
        ref={buttonRef}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Switch repository, current: ${repository.name}`}
        className="flex h-9 max-w-[260px] items-center gap-2 rounded-[8px] px-2.5 font-display text-[16px] italic text-text-primary transition-colors hover:bg-surface-2"
      >
        <span className="truncate">{repository.name}</span>
        <ChevronDown size={14} className="flex-none text-text-tertiary" aria-hidden="true" />
      </button>
      {open && (
        <div
          ref={menuRef}
          role="menu"
          aria-label="Repositories"
          onKeyDown={onMenuKey}
          className="cs-glass cs-fade-in absolute right-0 top-[calc(100%+6px)] z-50 w-[min(340px,calc(100vw-20px))] rounded-[10px] border border-border-strong p-1.5 shadow-[inset_0_1px_0_oklch(1_0_0/0.07)]"
        >
          {repos.map((r) => (
            <Link
              key={r.id}
              href={`/r/${r.id}`}
              role="menuitem"
              onClick={() => setOpen(false)}
              className="flex items-center justify-between gap-3 rounded-[7px] px-2.5 py-2 !outline-none hover:bg-surface-3 focus-visible:bg-surface-3"
              aria-current={r.id === repository.id ? "true" : undefined}
            >
              <span className="truncate font-display text-[15.5px] italic text-text-primary">{r.name}</span>
              <RepoStatusChip status={r.status} indexingStatus={r.indexing_status} />
            </Link>
          ))}
          <div className="mx-1 my-1.5 h-px bg-border-subtle" />
          <Link
            href="/"
            role="menuitem"
            onClick={() => setOpen(false)}
            className="flex items-center justify-between rounded-[7px] px-2.5 py-2 text-[13px] text-text-secondary !outline-none hover:bg-surface-3 hover:text-text-primary focus-visible:bg-surface-3"
          >
            All repositories
            <ArrowRight size={14} aria-hidden="true" />
          </Link>
        </div>
      )}
    </div>
  );
}
