"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { useRepositoryContext } from "@/context/RepositoryContext";
import { TopologyMark } from "@/components/devices/TopologyMark";
import { FileTree, type FileMarker } from "@/components/domain/FileTree";
import { ErrorPanel, Notice } from "@/components/state/StateVocabulary";
import { buildModuleIndex, fileToModule, flattenTreeFiles, isFolderNode } from "@/lib/graphModel";
import { useCallGraph, useDependencyGraph, useIntelligence, useSymbols, useTree } from "@/lib/query/workspace";
import type { SymbolExplorerItem, TreeNode } from "@/lib/types/workspace";
import { cn } from "@/lib/utils";

const PARSED_EXT = /\.(py|pyi|js|jsx|mjs|cjs|ts|tsx|java)$/i;

function formatSize(b?: number | null): string {
  if (b == null) return "";
  if (b >= 1e6) return `${(b / 1e6).toFixed(1)} MB`;
  if (b >= 1e3) return `${(b / 1e3).toFixed(1)} KB`;
  return `${b} B`;
}

export default function ExplorerPage() {
  const { repositoryId, isReady } = useRepositoryContext();
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const tree = useTree(repositoryId);
  const symbols = useSymbols(repositoryId, { enabled: isReady });
  const intelligence = useIntelligence(repositoryId, { enabled: isReady });
  const depGraph = useDependencyGraph(repositoryId, { enabled: isReady });
  const callGraph = useCallGraph(repositoryId, { enabled: isReady });

  const fileParam = searchParams.get("file");
  const lineParam = Number(searchParams.get("line")) || null;
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [openSymbol, setOpenSymbol] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState("all");
  const [mobileDetail, setMobileDetail] = useState(Boolean(fileParam));

  const files = useMemo(() => flattenTreeFiles(tree.data?.root), [tree.data]);
  const fileByPath = useMemo(() => new Map(files.map((f) => [f.path, f])), [files]);
  const moduleIndex = useMemo(() => buildModuleIndex(files.map((f) => f.path)), [files]);
  const selected = fileParam ? fileByPath.get(fileParam) ?? null : null;
  const I = intelligence.data;

  // Top-level folders open by default; the selected file's ancestors always open.
  useEffect(() => {
    if (!tree.data) return;
    setExpanded((prev) => {
      const next = new Set(prev);
      if (prev.size === 0) tree.data.root.filter(isFolderNode).slice(0, 1).forEach((n) => next.add(n.path));
      if (fileParam) {
        const parts = fileParam.split("/");
        for (let i = 1; i < parts.length; i++) next.add(parts.slice(0, i).join("/"));
      }
      return next;
    });
  }, [tree.data, fileParam]);

  const markers = useMemo(() => {
    const m = new Map<string, FileMarker>();
    if (!I) return m;
    I.orphan_files.forEach((p) => m.set(p, "orphan"));
    I.dependency_hotspots.slice(0, 5).forEach((h) => {
      const f = moduleIndex.get(h.module_path);
      if (f) m.set(f, "hotspot");
    });
    I.entry_points.forEach((p) => m.set(p, "entry"));
    return m;
  }, [I, moduleIndex]);

  const fileSymbols = useMemo(() => (selected ? (symbols.data?.symbols ?? []).filter((s) => s.file_path === selected.path) : []), [symbols.data, selected]);

  // Deep link: ?line= opens the symbol that starts there (innermost first).
  useEffect(() => {
    if (!lineParam || fileSymbols.length === 0) return;
    const hit = fileSymbols.filter((s) => s.start_line === lineParam).sort((a, b) => (a.parent_symbol_id ? -1 : 1) - (b.parent_symbol_id ? -1 : 1))[0]
      ?? fileSymbols.filter((s) => s.start_line <= lineParam && s.end_line >= lineParam).sort((a, b) => a.end_line - a.start_line - (b.end_line - b.start_line))[0];
    if (hit) {
      setOpenSymbol(hit.id);
      setTypeFilter("all");
      requestAnimationFrame(() => document.getElementById(`sym-${hit.id}`)?.scrollIntoView({ block: "center" }));
    }
  }, [lineParam, fileSymbols]);

  function select(node: TreeNode) {
    setOpenSymbol(null);
    setMobileDetail(true);
    router.replace(`${pathname}?file=${encodeURIComponent(node.path)}`);
  }

  const mod = selected ? fileToModule(selected.path) : null;
  const importedBy = useMemo(
    () => (mod && depGraph.data ? [...new Set(depGraph.data.edges.filter((e) => e.target === mod).map((e) => e.source))] : []),
    [mod, depGraph.data],
  );
  const imports = useMemo(
    () => (mod && depGraph.data ? [...new Set(depGraph.data.edges.filter((e) => e.source === mod).map((e) => e.target))] : []),
    [mod, depGraph.data],
  );
  const cycle = mod ? I?.circular_dependencies.find((c) => c.includes(mod)) : undefined;
  const hotspot = mod ? I?.dependency_hotspots.find((h) => h.module_path === mod) : undefined;

  const types = [...new Set(fileSymbols.map((s) => s.symbol_type))];
  const visible = fileSymbols.filter((s) => typeFilter === "all" || s.symbol_type === typeFilter);
  const visibleIds = new Set(visible.map((s) => s.id));
  const roots = visible.filter((s) => !s.parent_symbol_id || !visibleIds.has(s.parent_symbol_id)).sort((a, b) => a.start_line - b.start_line);
  const childrenOf = (s: SymbolExplorerItem) => visible.filter((k) => k.parent_symbol_id === s.id).sort((a, b) => a.start_line - b.start_line);

  const renderRef = (m: string) => {
    const f = moduleIndex.get(m);
    return f ? (
      <Link key={m} href={`${pathname}?file=${encodeURIComponent(f)}`} className="block break-all border-t border-border-subtle py-[7px] font-mono text-[12px] text-text-secondary transition-colors hover:text-[var(--cs-accent-violet-hover)]">
        {f}
      </Link>
    ) : (
      <span key={m} className="block break-all border-t border-border-subtle py-[7px] font-mono text-[12px] text-text-tertiary">
        {m}
      </span>
    );
  };

  const renderSymbol = (s: SymbolExplorerItem, child?: boolean) => {
    const open = openSymbol === s.id;
    const callers = open ? (callGraph.data?.edges ?? []).filter((e) => e.target === s.qualified_name).map((e) => e.source) : [];
    const callees = open ? (callGraph.data?.edges ?? []).filter((e) => e.source === s.qualified_name).map((e) => e.target) : [];
    return (
      <div id={`sym-${s.id}`} className="border-t border-border-subtle">
        <button
          onClick={() => setOpenSymbol(open ? null : s.id)}
          aria-expanded={open}
          className={cn(
            "grid w-full grid-cols-[minmax(0,1fr)_auto] items-baseline gap-3 rounded-[6px] py-[11px] pr-2 text-left transition-colors hover:bg-surface-1",
            child ? "pl-[30px]" : "pl-2",
            open && "bg-surface-1 shadow-[inset_2px_0_0_var(--cs-accent-violet)]",
          )}
        >
          <span className="min-w-0">
            <span className="font-mono text-[13px] font-medium text-violet">{s.name}</span>
            <span className="ml-2 font-mono text-[11px] text-text-tertiary">
              {s.symbol_type}
              {s.visibility !== "public" ? ` · ${s.visibility}` : ""}
            </span>
            {s.signature && <span className="mt-0.5 block break-words font-mono text-[11.5px] text-text-tertiary">{s.signature}</span>}
          </span>
          <span className="cs-tabular whitespace-nowrap font-mono text-[11.5px] text-text-secondary">
            {s.start_line}
            {s.end_line !== s.start_line ? `–${s.end_line}` : ""}
          </span>
        </button>
        {open && (
          <div className="cs-fade-in pb-[18px] pl-[34px] pr-2 pt-1.5">
            <dl className="cs-kv">
              <dt>qualified</dt>
              <dd>{s.qualified_name}</dd>
              <dt>callers</dt>
              <dd>{callGraph.isLoading ? "loading…" : callers.length ? callers.map((c) => <span key={c} className="block">{c}</span>) : "none resolved"}</dd>
              <dt>calls</dt>
              <dd>{callGraph.isLoading ? "loading…" : callees.length ? callees.map((c) => <span key={c} className="block">{c}</span>) : "none resolved"}</dd>
            </dl>
            <div className="mt-3 flex flex-wrap gap-x-3.5 gap-y-1">
              <Link className="cs-link" href={`/r/${repositoryId}/ask?q=${encodeURIComponent(`Explain ${s.qualified_name}`)}`}>
                ask about this symbol <ArrowRight size={13} aria-hidden="true" />
              </Link>
              {callers.length + callees.length > 0 && (
                <Link className="cs-link cs-link-quiet" href={`/r/${repositoryId}/graph?mode=call&focus=${encodeURIComponent(s.qualified_name)}`}>
                  show in call graph
                </Link>
              )}
              <Link className="cs-link cs-link-quiet" href={`/r/${repositoryId}/search?q=${encodeURIComponent(s.name)}`}>
                search
              </Link>
            </div>
          </div>
        )}
      </div>
    );
  };

  return (
    <div className={cn("grid h-full min-h-0 grid-cols-1 md:grid-cols-[270px_minmax(0,1fr)] xl:grid-cols-[320px_minmax(0,1fr)]")}>
      <div className={cn("cs-scrollbar min-h-0 overflow-y-auto border-border-subtle px-3.5 pb-10 pt-6 md:border-r", mobileDetail && selected && "hidden md:block")}>
        <div className="flex items-baseline justify-between px-1">
          <p className="cs-mono-label">File tree</p>
          {tree.data && <span className="cs-monoline !text-[11px]">{files.length} files</span>}
        </div>
        {I && (
          <div className="mt-2 flex flex-wrap gap-3 px-1 font-mono text-[11px] text-text-tertiary">
            <span className="inline-flex items-center gap-1.5"><i className="h-1.5 w-1.5 rounded-full bg-cyan" aria-hidden="true" />entry</span>
            <span className="inline-flex items-center gap-1.5"><i className="h-1.5 w-1.5 rounded-full bg-violet" aria-hidden="true" />hotspot</span>
            <span className="inline-flex items-center gap-1.5"><i className="h-1.5 w-1.5 rounded-full border border-dotted border-text-tertiary" aria-hidden="true" />orphan</span>
          </div>
        )}
        <div className="mt-2.5">
          {tree.isLoading && [0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="cs-skel my-2 h-5" style={{ opacity: 1 - i * 0.14 }} />)}
          {tree.isError && <ErrorPanel error={tree.error} onRetry={() => tree.refetch()} />}
          {tree.data && tree.data.root.length === 0 && <p className="py-6 text-text-secondary">No files scanned yet.</p>}
          {tree.data && tree.data.root.length > 0 && (
            <FileTree
              nodes={tree.data.root}
              expanded={expanded}
              onToggle={(p) => setExpanded((prev) => { const n = new Set(prev); if (n.has(p)) n.delete(p); else n.add(p); return n; })}
              onSelect={select}
              selectedPath={selected?.path ?? null}
              markers={markers}
            />
          )}
        </div>
      </div>

      <div className={cn("cs-scrollbar min-h-0 min-w-0 overflow-y-auto px-5 pb-24 pt-8 sm:px-11", !(mobileDetail && selected) && "hidden md:block")}>
        {!selected && (
          <div className="grid min-h-[60vh] place-items-center text-center">
            <div className="flex flex-col items-center gap-4">
              <TopologyMark variant="mark" size={40} />
              <p className="text-text-secondary">{fileParam && tree.data ? `“${fileParam}” isn't in this repository's file tree.` : "Select a file to see its parsed symbols and relationships."}</p>
            </div>
          </div>
        )}
        {selected && (
          <>
            <button className="cs-disclosure-btn -ml-1 mb-2 md:hidden" onClick={() => setMobileDetail(false)}>
              <ArrowLeft size={13} aria-hidden="true" /> File tree
            </button>
            <h1 className="font-display text-[26px] italic leading-tight text-text-primary">{selected.name}</h1>
            <p className="cs-monoline mt-1">{selected.path}</p>
            <div className="mt-3 flex flex-wrap gap-1.5">
              <span className="cs-badge">{selected.language ?? "not classified"}</span>
              {selected.size_bytes != null && <span className="cs-badge">{formatSize(selected.size_bytes)}</span>}
              {I?.entry_points.includes(selected.path) && <span className="cs-badge !bg-[var(--cs-cyan-tint)] !text-cyan">entry point</span>}
              {hotspot && <span className="cs-badge !bg-[var(--cs-violet-tint)] !text-violet">hotspot · {hotspot.incoming_dependencies} dependents</span>}
              {I?.orphan_files.includes(selected.path) && <span className="cs-badge border border-dotted border-border-strong !bg-transparent !text-text-tertiary">orphan</span>}
            </div>

            {!isReady && (
              <Notice className="mt-6">Symbol intelligence unlocks once indexing finishes — the raw file path and size are shown above in the meantime.</Notice>
            )}

            {isReady && (
              <>
                {cycle && (
                  <Notice tone="warn" className="mt-6" title="Part of a circular dependency">
                    <span className="font-mono text-[12px]">{[...cycle, cycle[0]].join(" → ")}</span>
                  </Notice>
                )}
                <div className="mt-8 flex flex-wrap items-baseline justify-between gap-2">
                  <p className="cs-mono-label">Parsed symbols · {fileSymbols.length}</p>
                  <Link href={`/r/${repositoryId}/ask?q=${encodeURIComponent(`Explain ${selected.path}`)}`} className="cs-link">
                    ask about this file <ArrowRight size={13} aria-hidden="true" />
                  </Link>
                </div>
                {types.length > 1 && (
                  <div className="mt-3 flex flex-wrap gap-1.5" role="group" aria-label="Filter by symbol type">
                    {["all", ...types].map((t) => (
                      <button key={t} className="cs-chipbtn" aria-pressed={typeFilter === t} onClick={() => setTypeFilter(t)}>
                        {t}
                      </button>
                    ))}
                  </div>
                )}
                <div className="mt-3 border-b border-border-subtle">
                  {symbols.isLoading && [0, 1, 2].map((i) => <div key={i} className="cs-skel my-2.5 h-9" />)}
                  {symbols.isError && <ErrorPanel error={symbols.error} onRetry={() => symbols.refetch()} />}
                  {symbols.data && fileSymbols.length === 0 && (
                    <p className="border-t border-border-subtle py-6 text-text-secondary">
                      No parsed symbols for this file.{" "}
                      {PARSED_EXT.test(selected.path) ? "The parser found no top-level definitions." : "CodeSage parses Python, JavaScript, TypeScript and Java."}
                    </p>
                  )}
                  {roots.map((s) => (
                    <div key={s.id}>
                      {renderSymbol(s)}
                      {childrenOf(s).map((c) => (
                        <div key={c.id}>{renderSymbol(c, true)}</div>
                      ))}
                    </div>
                  ))}
                </div>
                {(importedBy.length > 0 || imports.length > 0) && (
                  <div className="mt-7 grid grid-cols-1 gap-7 md:grid-cols-2">
                    <div>
                      <p className="cs-mono-label">Imported by · {importedBy.length}</p>
                      <div className="mt-2">{importedBy.length ? importedBy.map(renderRef) : <p className="mt-2 text-small text-text-tertiary">Nothing imports this file.</p>}</div>
                    </div>
                    <div>
                      <p className="cs-mono-label">Imports · {imports.length}</p>
                      <div className="mt-2">{imports.length ? imports.map(renderRef) : <p className="mt-2 text-small text-text-tertiary">No resolved internal imports.</p>}</div>
                    </div>
                  </div>
                )}
                {mod && depGraph.data?.nodes.includes(mod) && (
                  <Link href={`/r/${repositoryId}/graph?focus=${encodeURIComponent(mod)}`} className="cs-link mt-6">
                    open in Graph <ArrowRight size={13} aria-hidden="true" />
                  </Link>
                )}
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
