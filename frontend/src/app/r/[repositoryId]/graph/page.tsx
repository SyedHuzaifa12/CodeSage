"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo } from "react";
import { ArrowRight, RotateCcw, X } from "lucide-react";
import { useRepositoryContext } from "@/context/RepositoryContext";
import { RequireReady } from "@/components/nav/RequireReady";
import { GraphCanvas } from "@/components/graph/GraphCanvas";
import { GraphLegend } from "@/components/domain/GraphLegend";
import { TopologyDiagram } from "@/components/domain/TopologyDiagram";
import { TopologyMark } from "@/components/devices/TopologyMark";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Modal } from "@/components/ui/Modal";
import { ErrorPanel } from "@/components/state/StateVocabulary";
import { useBreakpoint } from "@/hooks/useMediaQuery";
import { DEFAULT_GRAPH_NODE_CAP } from "@/lib/graphCap";
import { buildGraphModel, buildModuleIndex, cycleEdgeKeys, fileToModule, flattenTreeFiles, moduleAreas, type GraphModel } from "@/lib/graphModel";
import { useCallGraph, useDependencyGraph, useIntelligence, useSymbols, useTree } from "@/lib/query/workspace";
import type { IntelligenceResponse, SymbolExplorerItem } from "@/lib/types/workspace";

type Mode = "dependency" | "call";

function Inspector({
  node,
  mode,
  model,
  intelligence,
  file,
  symbols,
  repositoryId,
  onFocus,
  onClose,
}: {
  node: string | null;
  mode: Mode;
  model: GraphModel;
  intelligence?: IntelligenceResponse;
  file: string | null;
  symbols: SymbolExplorerItem[];
  repositoryId: string;
  onFocus: (n: string) => void;
  onClose?: () => void;
}) {
  const cycles = intelligence?.circular_dependencies ?? [];
  if (!node) {
    return (
      <div>
        <p className="cs-mono-label">Inspector</p>
        <p className="mt-2 text-small text-text-secondary">
          Select a node to inspect its relationships and symbols. Arrow keys move between connected nodes once one is focused; Esc clears.
        </p>
        {mode === "dependency" && (
          <>
            <p className="cs-mono-label mt-8">Cycles · {cycles.length}</p>
            <div className="mt-2">
              {cycles.length === 0 && <p className="border-t border-border-subtle py-2 font-mono text-[12px] text-text-secondary">No circular dependencies.</p>}
              {cycles.map((c) => (
                <button
                  key={c.join(">")}
                  onClick={() => onFocus(c[0])}
                  className="flex w-full items-start gap-2 border-t border-border-subtle py-2 text-left font-mono text-[12px] text-text-secondary hover:text-[var(--cs-accent-violet-hover)]"
                >
                  <RotateCcw size={12} className="mt-1 flex-none text-danger" aria-hidden="true" />
                  <span className="break-all">{[...c, c[0]].join(" → ")}</span>
                </button>
              ))}
            </div>
            <p className="cs-mono-label mt-8">Orphan files · {intelligence?.orphan_files.length ?? 0}</p>
            <div className="mt-2">
              {(intelligence?.orphan_files ?? []).map((f) => (
                <Link
                  key={f}
                  href={`/r/${repositoryId}/explorer?file=${encodeURIComponent(f)}`}
                  className="block break-all border-t border-border-subtle py-2 font-mono text-[12px] text-text-secondary hover:text-text-primary"
                >
                  {f}
                </Link>
              ))}
            </div>
          </>
        )}
      </div>
    );
  }
  const incoming = model.allEdges.filter((e) => e.target === node).map((e) => e.source);
  const outgoing = model.allEdges.filter((e) => e.source === node).map((e) => e.target);
  const cycle = mode === "dependency" ? cycles.find((c) => c.includes(node)) : undefined;
  const hot = mode === "dependency" ? intelligence?.dependency_hotspots.find((h) => h.module_path === node) : undefined;
  const orphan = mode === "dependency" && file ? intelligence?.orphan_files.includes(file) : false;
  const question =
    mode === "call" ? `What calls ${node.split(".").pop()}()?` : `Which modules depend on ${file ?? node}?`;
  const list = (items: string[]) =>
    items.length === 0 ? (
      <p className="mt-1 text-small text-text-tertiary">None resolved.</p>
    ) : (
      <>
        {items.slice(0, 10).map((x) => (
          <button
            key={x}
            onClick={() => onFocus(x)}
            className="block w-full break-all border-t border-border-subtle py-[7px] text-left font-mono text-[12px] text-text-secondary hover:text-[var(--cs-accent-violet-hover)]"
          >
            {x}
          </button>
        ))}
        {items.length > 10 && <p className="border-t border-border-subtle py-[7px] font-mono text-[12px] text-text-tertiary">+{items.length - 10} more</p>}
      </>
    );
  return (
    <div className="relative">
      {onClose && (
        <button onClick={onClose} aria-label="Close inspector" className="absolute right-0 top-0 grid h-8 w-8 place-items-center rounded-md text-text-tertiary hover:bg-surface-2 hover:text-text-primary">
          <X size={15} aria-hidden="true" />
        </button>
      )}
      <p className="cs-mono-label">Inspector</p>
      <h2 className="mt-2 break-all pr-8 font-display text-[19px] italic leading-snug text-text-primary">{node}</h2>
      <p className="cs-monoline mt-1 !text-[11px]">
        {incoming.length + outgoing.length} connections · {symbols.length} symbols
      </p>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {hot && <span className="cs-badge !bg-[var(--cs-violet-tint)] !text-violet">hotspot · {hot.incoming_dependencies}</span>}
        {cycle && <span className="cs-badge !bg-[var(--cs-danger-tint)] !text-danger">in a cycle</span>}
        {orphan && <span className="cs-badge border border-dotted border-border-strong !bg-transparent !text-text-tertiary">orphan</span>}
        {file && <span className="cs-badge break-all">{file}</span>}
      </div>
      {cycle && <p className="mt-3 break-all font-mono text-[11.5px] text-danger">{[...cycle, cycle[0]].join(" → ")}</p>}
      <Link href={`/r/${repositoryId}/ask?q=${encodeURIComponent(question)}`} className="cs-link mt-4">
        ask about this node <ArrowRight size={13} aria-hidden="true" />
      </Link>
      <p className="cs-mono-label mt-6">
        {mode === "call" ? "Callers" : "Imported by"} · {incoming.length}
      </p>
      <div className="mt-1.5">{list(incoming)}</div>
      <p className="cs-mono-label mt-6">
        {mode === "call" ? "Calls" : "Imports"} · {outgoing.length}
      </p>
      <div className="mt-1.5">{list(outgoing)}</div>
      <p className="cs-mono-label mt-6">Symbols</p>
      <div className="mt-1.5">
        {symbols.length === 0 && <p className="text-small text-text-tertiary">No parsed symbols for this node.</p>}
        {symbols.slice(0, 20).map((s) => (
          <Link
            key={s.id}
            href={`/r/${repositoryId}/explorer?file=${encodeURIComponent(s.file_path)}&line=${s.start_line}`}
            className="block border-t border-border-subtle py-[7px] font-mono text-[12px] hover:bg-surface-1"
          >
            <span className="text-violet">{s.name}</span>{" "}
            <span className="text-text-tertiary">
              {s.symbol_type} · {s.start_line}–{s.end_line}
            </span>
          </Link>
        ))}
        {symbols.length > 20 && <p className="border-t border-border-subtle py-[7px] font-mono text-[12px] text-text-tertiary">+{symbols.length - 20} more in Explorer</p>}
      </div>
      {file && (
        <Link href={`/r/${repositoryId}/explorer?file=${encodeURIComponent(file)}`} className="cs-link cs-link-quiet mt-4">
          open file in Explorer <ArrowRight size={13} aria-hidden="true" />
        </Link>
      )}
    </div>
  );
}

function GraphInner() {
  const { repositoryId } = useRepositoryContext();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const breakpoint = useBreakpoint();
  const mode: Mode = params.get("mode") === "call" ? "call" : "dependency";
  const focus = params.get("focus");
  const area = params.get("area") ?? "all";

  const depGraph = useDependencyGraph(repositoryId);
  const callGraph = useCallGraph(repositoryId, { enabled: mode === "call" });
  const intelligence = useIntelligence(repositoryId);
  const symbols = useSymbols(repositoryId);
  const tree = useTree(repositoryId);
  const active = mode === "dependency" ? depGraph : callGraph;

  const setParams = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === "" || (k === "mode" && v === "dependency") || (k === "area" && v === "all")) next.delete(k);
      else next.set(k, v);
    }
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  };

  const moduleIndex = useMemo(() => buildModuleIndex(flattenTreeFiles(tree.data?.root).map((f) => f.path)), [tree.data]);
  const areas = useMemo(() => moduleAreas(active.data?.nodes ?? []), [active.data]);
  const model = useMemo(
    () => (active.data ? buildGraphModel(active.data.nodes, active.data.edges, { cap: DEFAULT_GRAPH_NODE_CAP, prefix: area }) : null),
    [active.data, area],
  );
  const cycleKeys = useMemo(() => cycleEdgeKeys(depGraph.data?.circular_dependencies ?? []), [depGraph.data]);
  const hotspots = useMemo(() => new Set((intelligence.data?.dependency_hotspots ?? []).slice(0, 5).map((h) => h.module_path)), [intelligence.data]);
  const orphans = useMemo(() => new Set((intelligence.data?.orphan_files ?? []).map(fileToModule)), [intelligence.data]);

  const selected = focus && model?.nodes.includes(focus) ? focus : null;
  const allSymbols = useMemo(() => symbols.data?.symbols ?? [], [symbols.data]);
  const focusFile = selected
    ? mode === "dependency"
      ? moduleIndex.get(selected) ?? null
      : allSymbols.find((s) => s.qualified_name === selected)?.file_path ?? null
    : null;
  const focusSymbols = useMemo(() => {
    if (!selected) return [];
    if (mode === "call") {
      const sym = allSymbols.find((s) => s.qualified_name === selected);
      return sym ? [sym, ...allSymbols.filter((s) => s.parent_symbol_id === sym.id)] : [];
    }
    return focusFile ? allSymbols.filter((s) => s.file_path === focusFile) : [];
  }, [selected, mode, allSymbols, focusFile]);

  const focusNode = (n: string | null) => {
    if (n && model && !model.nodes.includes(n)) setParams({ focus: n, area: null });
    else setParams({ focus: n });
  };

  const unit = mode === "call" ? "symbols" : "modules";

  if (breakpoint === "mobile") {
    return (
      <div className="px-5 pb-24 pt-8">
        <p className="cs-mono-label">Knowledge map</p>
        <p className="cs-lede mt-2 !text-[17px]">The interactive graph is best explored on a larger screen.</p>
        {depGraph.data && (
          <div className="mt-4">
            <TopologyDiagram
              nodes={depGraph.data.nodes}
              edges={depGraph.data.edges}
              hotspots={hotspots}
              cycles={depGraph.data.circular_dependencies}
              orphans={orphans}
              width={600}
              height={520}
              layoutKey={`mobile-${repositoryId}`}
            />
          </div>
        )}
        {model && (
          <>
            <p className="cs-mono-label mt-6">Most connected {unit}</p>
            <div className="mt-2">
              {model.nodes.slice(0, 10).map((n) => (
                <Link
                  key={n}
                  href={`/r/${repositoryId}/ask?q=${encodeURIComponent(mode === "call" ? `What calls ${n.split(".").pop()}()?` : `Which modules depend on ${moduleIndex.get(n) ?? n}?`)}`}
                  className="grid grid-cols-[minmax(0,1fr)_34px] border-t border-border-subtle py-2.5 font-mono text-[12px] text-text-secondary"
                >
                  <span className="truncate">{n}</span>
                  <b className="text-right font-medium text-text-primary">{model.degree.get(n)}</b>
                </Link>
              ))}
            </div>
          </>
        )}
      </div>
    );
  }

  const inspector = model && (
    <Inspector
      node={selected}
      mode={mode}
      model={model}
      intelligence={intelligence.data}
      file={focusFile}
      symbols={focusSymbols}
      repositoryId={repositoryId}
      onFocus={focusNode}
      onClose={breakpoint === "tablet" ? () => focusNode(null) : undefined}
    />
  );

  return (
    <div className="grid h-full min-h-0 grid-cols-1 xl:grid-cols-[minmax(0,1fr)_300px]">
      <div className="flex min-h-0 min-w-0 flex-col">
        <div className="flex flex-wrap items-center gap-x-[18px] gap-y-3 border-b border-border-subtle px-6 py-4">
          <h1 className="font-display text-[26px] italic tracking-[-0.015em] text-text-primary">Knowledge map</h1>
          <SegmentedControl
            aria-label="Graph type"
            value={mode}
            onChange={(v) => setParams({ mode: v, focus: null, area: null })}
            options={[
              { value: "dependency", label: "Dependency" },
              { value: "call", label: "Call graph" },
            ]}
          />
          <span className="flex-1" />
          {model && (
            <span className="cs-monoline !text-[11px]">
              top {model.nodes.length} of {model.totalNodes.toLocaleString("en-US")} {unit} · sized by connectivity
            </span>
          )}
        </div>
        {areas.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 border-b border-border-subtle px-6 py-2.5">
            <span className="cs-mono-label mr-1">Focus area</span>
            {["all", ...areas].map((a) => (
              <button key={a} className="cs-chipbtn" aria-pressed={area === a} onClick={() => setParams({ area: a, focus: null })}>
                {a}
              </button>
            ))}
            <span className="cs-tag text-cyan" title="Filters the loaded graph in the browser — no server-side filtering">
              client-side
            </span>
          </div>
        )}
        <div className="relative min-h-[360px] flex-1">
          {active.isLoading && <div className="cs-skel absolute inset-8" />}
          {active.isError && (
            <div className="p-8">
              <ErrorPanel error={active.error} onRetry={() => active.refetch()} />
            </div>
          )}
          {model && model.nodes.length === 0 && (
            <div className="grid h-full place-items-center text-center">
              <div className="flex flex-col items-center gap-3">
                <TopologyMark variant="mark" size={36} />
                <p className="text-text-secondary">No resolved relationships yet for this graph type.</p>
              </div>
            </div>
          )}
          {model && model.nodes.length > 0 && (
            <GraphCanvas
              model={model}
              mode={mode}
              hotspots={hotspots}
              orphans={orphans}
              cycleKeys={cycleKeys}
              selected={selected}
              onSelect={focusNode}
              layoutKey={`${repositoryId}-${mode}-${area}`}
            />
          )}
          <p className="sr-only" role="status">
            {model ? `Graph: ${model.nodes.length} nodes shown of ${model.totalNodes}, ${model.edges.length} edges.${selected ? ` Selected ${selected}.` : ""}` : "Loading graph."}
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t border-border-subtle px-6 py-2.5">
          <GraphLegend mode={mode} cycles={(depGraph.data?.circular_dependencies.length ?? 0) > 0} />
          {model && (
            <span className="cs-monoline !text-[11px]">
              {model.nodes.length} nodes shown, {model.edges.length} edges · every edge is observed
            </span>
          )}
        </div>
      </div>
      <aside
        aria-label="Graph inspector"
        className="cs-scrollbar hidden min-h-0 overflow-y-auto border-l border-border-subtle bg-[linear-gradient(180deg,oklch(0.163_0.007_280),var(--cs-bg)_55%)] px-[22px] pb-10 pt-6 xl:block"
        aria-live="polite"
      >
        {inspector}
      </aside>
      {breakpoint === "tablet" && (
        <Modal open={Boolean(selected)} onOpenChange={(o) => !o && focusNode(null)} title="Inspector" side="right">
          {inspector}
        </Modal>
      )}
    </div>
  );
}

export default function GraphPage() {
  return (
    <RequireReady>
      <GraphInner />
    </RequireReady>
  );
}
