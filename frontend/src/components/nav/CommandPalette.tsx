"use client";

import * as RadixDialog from "@radix-ui/react-dialog";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { BookOpen, ChevronRight, Code2, FileText, Folder, Info, MessageSquare, Search } from "lucide-react";
import { useRepositories } from "@/lib/query/repositories";
import { useSymbols, useTree } from "@/lib/query/workspace";
import { flattenTreeFiles } from "@/lib/graphModel";
import { NAV_ITEMS, SETTINGS_PATH } from "@/lib/nav";
import { isRepositoryReady, type Repository } from "@/lib/types/repository";
import { REPORT_TYPES, REPORT_TYPE_TITLES } from "@/lib/types/reports";

interface Item {
  group: string;
  icon: ReactNode;
  text: string;
  hint?: string;
  mono?: boolean;
  href?: string;
}

/**
 * ⌘K command palette — navigation only, over data the app already has
 * (repositories, the file tree, parsed symbols). "Ask …" and "Search …"
 * hand the typed text to the real Ask and Search pages.
 */
export function CommandPalette({
  open,
  onOpenChange,
  repository,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  repository?: Repository;
}) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);
  const ready = repository ? isRepositoryReady(repository) : false;
  const repos = useRepositories();
  const tree = useTree(open && repository && repository.status === "ready" ? repository.id : undefined);
  const symbols = useSymbols(open && ready ? repository?.id : undefined);

  useEffect(() => {
    if (open) {
      setQ("");
      setSel(0);
    }
  }, [open]);

  const items = useMemo<Item[]>(() => {
    const ql = q.trim().toLowerCase();
    const out: Item[] = [];
    const id = repository?.id;
    if (id && ready && q.trim().length > 2) {
      out.push({ group: "Actions", icon: <MessageSquare size={15} />, text: `Ask CodeSage: “${q.trim()}”`, hint: "ask", href: `/r/${id}/ask?q=${encodeURIComponent(q.trim())}` });
      out.push({ group: "Actions", icon: <Search size={15} />, text: `Search: “${q.trim()}”`, hint: "hybrid retrieval", href: `/r/${id}/search?q=${encodeURIComponent(q.trim())}` });
    }
    if (id && repository) {
      const pages = [
        ...NAV_ITEMS.map((n) => ({ label: n.label, num: n.num, href: n.path(id), gated: !n.reachableBeforeReady })),
        { label: "Index & Settings", num: "", href: SETTINGS_PATH(id), gated: false },
      ];
      for (const p of pages) {
        if (ql && !p.label.toLowerCase().includes(ql)) continue;
        const locked = p.gated && !ready;
        out.push({ group: repository.name, icon: <ChevronRight size={15} />, text: p.label, hint: locked ? "indexing required" : p.num, href: locked ? undefined : p.href });
      }
      if (ready) {
        for (const t of REPORT_TYPES) {
          const title = REPORT_TYPE_TITLES[t];
          if (ql && title.toLowerCase().includes(ql)) out.push({ group: "Reports", icon: <BookOpen size={15} />, text: title, href: `/r/${id}/reports/${t}` });
        }
      }
      if (ql) {
        const files = flattenTreeFiles(tree.data?.root).filter((f) => f.path.toLowerCase().includes(ql)).slice(0, 6);
        for (const f of files) out.push({ group: "Files", icon: <FileText size={15} />, text: f.path, mono: true, hint: "explorer", href: `/r/${id}/explorer?file=${encodeURIComponent(f.path)}` });
        const syms = (symbols.data?.symbols ?? []).filter((s) => s.name.toLowerCase().includes(ql)).slice(0, 6);
        for (const s of syms) out.push({ group: "Symbols", icon: <Code2 size={15} />, text: s.qualified_name, mono: true, hint: s.symbol_type, href: `/r/${id}/explorer?file=${encodeURIComponent(s.file_path)}&line=${s.start_line}` });
      }
    }
    for (const r of repos.data?.repositories ?? []) {
      if (ql && !r.name.toLowerCase().includes(ql)) continue;
      out.push({ group: "Repositories", icon: <Folder size={15} />, text: r.name, hint: r.status === "failed" ? "failed" : isRepositoryReady(r) ? "indexed" : r.indexing_status === "indexing" ? "indexing" : "not indexed", href: `/r/${r.id}` });
    }
    for (const [text, href] of [["How CodeSage works", "/about"], ["All repositories", "/"]] as const) {
      if (!ql || text.toLowerCase().includes(ql)) out.push({ group: "CodeSage", icon: <Info size={15} />, text, href });
    }
    return out;
  }, [q, repository, ready, repos.data, tree.data, symbols.data]);

  const safeSel = Math.min(sel, Math.max(0, items.length - 1));
  const go = (i: number) => {
    const it = items[i];
    if (!it?.href) return;
    onOpenChange(false);
    router.push(it.href);
  };

  function onKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSel((s) => Math.min(items.length - 1, s + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSel((s) => Math.max(0, s - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      go(safeSel);
    }
  }

  useEffect(() => {
    listRef.current?.querySelector(`[data-i="${safeSel}"]`)?.scrollIntoView({ block: "nearest" });
  }, [safeSel]);

  let lastGroup = "";
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-40 bg-[oklch(0.1_0.01_280/0.72)] backdrop-blur-[3px] data-[state=open]:animate-cs-fade-in" />
        <RadixDialog.Content
          className="cs-glass fixed left-1/2 top-[12vh] z-50 w-[min(640px,calc(100vw-24px))] -translate-x-1/2 overflow-hidden rounded-[14px] border border-border-strong shadow-[inset_0_1px_0_oklch(1_0_0/0.07)] focus:outline-none"
          aria-describedby={undefined}
        >
          <RadixDialog.Title className="sr-only">Command palette</RadixDialog.Title>
          <div className="flex items-center gap-3 border-b border-border-subtle px-[18px]">
            <Search size={18} className="text-text-tertiary" aria-hidden="true" />
            <input
              autoFocus
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setSel(0);
              }}
              onKeyDown={onKey}
              placeholder={repository ? `Jump within ${repository.name}, or type a question…` : "Jump to a repository or page…"}
              aria-label="Command palette"
              role="combobox"
              aria-expanded="true"
              aria-controls="cs-palette-list"
              aria-activedescendant={`cs-pi-${safeSel}`}
              className="h-[58px] min-w-0 flex-1 bg-transparent font-display text-[19px] italic text-text-primary !outline-none placeholder:text-text-tertiary"
            />
          </div>
          <div ref={listRef} id="cs-palette-list" role="listbox" className="cs-scrollbar max-h-[min(440px,58vh)] overflow-y-auto p-1.5">
            {items.length === 0 && <div className="cs-mono-label px-3 py-3">No matches</div>}
            {items.map((it, i) => {
              const header = it.group !== lastGroup ? it.group : null;
              lastGroup = it.group;
              return (
                <div key={`${it.group}-${it.text}-${i}`}>
                  {header && <div className="cs-mono-label px-3 pb-1.5 pt-3">{header}</div>}
                  <button
                    id={`cs-pi-${i}`}
                    data-i={i}
                    role="option"
                    aria-selected={i === safeSel}
                    aria-disabled={!it.href || undefined}
                    onMouseEnter={() => setSel(i)}
                    onClick={() => go(i)}
                    className="flex min-h-[38px] w-full items-center gap-3 rounded-[8px] px-3 py-2 text-left text-[13px] text-text-secondary aria-disabled:opacity-45 aria-selected:bg-[linear-gradient(90deg,oklch(0.75_0.13_300/0.12),oklch(1_0_0/0.03))] aria-selected:text-text-primary aria-selected:shadow-[inset_2px_0_0_var(--cs-accent-violet)]"
                  >
                    <span className="flex-none text-text-tertiary" aria-hidden="true">
                      {it.icon}
                    </span>
                    <span className={it.mono ? "truncate font-mono text-[12px]" : "truncate"}>{it.text}</span>
                    {it.hint && <span className="ml-auto flex-none font-mono text-[10.5px] text-text-tertiary">{it.hint}</span>}
                  </button>
                </div>
              );
            })}
          </div>
          <div className="flex gap-4 border-t border-border-subtle px-4 py-2 font-mono text-[10.5px] text-text-tertiary">
            <span>↑↓ move</span>
            <span>↵ open</span>
            <span>esc close</span>
          </div>
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
