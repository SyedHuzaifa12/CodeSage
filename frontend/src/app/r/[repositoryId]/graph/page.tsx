"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ListTree, RotateCcw, Search, X } from "lucide-react";
import { useRepositoryContext } from "@/context/RepositoryContext";
import { RequireReady } from "@/components/nav/RequireReady";
import { GraphCanvas, type EdgeMode } from "@/components/graph/GraphCanvas";
import { GraphKey, GraphSummary, ModuleInspector, wordsFor, type GraphKind } from "@/components/graph/GraphPanels";
import { ModuleTable } from "@/components/graph/ModuleTable";
import { TopologyMark } from "@/components/devices/TopologyMark";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Modal } from "@/components/ui/Modal";
import { ErrorPanel } from "@/components/state/StateVocabulary";
import { useBreakpoint } from "@/hooks/useMediaQuery";
import { useGraphLayout } from "@/hooks/useGraphLayout";
import { buildModuleIndex, fileToModule, flattenTreeFiles, isParsedSourceFile } from "@/lib/graphModel";
import {
  DEFAULT_GROUP_LIMIT,
  buildGraphData,
  buildView,
  findTangles,
  groupsToReveal,
  searchModules,
  suggestExpansion,
  tangleIndex,
  type GraphView,
  type ModuleKind,
} from "@/lib/graph/model";
import { useCallGraph, useDependencyGraph, useIntelligence, useSymbols, useTree } from "@/lib/query/workspace";
import { cn } from "@/lib/utils";

/** More than this many boxes at once stops being a picture. Opening a folder that would pass it is refused, with a reason. */
const MAX_DRAWN = 320;
/** A loop larger than this is described in words, not drawn: marking dozens of boxes red shows nothing. */
const LOOP_MARK_LIMIT = 12;
const ALL_KINDS: ReadonlySet<ModuleKind> = new Set(["source", "test", "example", "external"]);
const NO_TANGLES: ReadonlyMap<string, number> = new Map();

function GraphInner() {
  const { repositoryId } = useRepositoryContext();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const breakpoint = useBreakpoint();
  const mode: GraphKind = params.get("mode") === "call" ? "call" : "dependency";
  const focus = params.get("focus");
  const layoutMode: "map" | "list" = params.get("view") === "map" ? "map" : params.get("view") === "list" ? "list" : breakpoint === "mobile" ? "list" : "map";
  const words = wordsFor(mode);

  const depGraph = useDependencyGraph(repositoryId);
  const callGraph = useCallGraph(repositoryId, { enabled: mode === "call" });
  const intelligence = useIntelligence(repositoryId);
  const symbols = useSymbols(repositoryId);
  const tree = useTree(repositoryId);
  const active = mode === "dependency" ? depGraph : callGraph;

  const setParams = useCallback(
    (patch: Record<string, string | null>) => {
      const next = new URLSearchParams(params.toString());
      for (const [k, v] of Object.entries(patch)) {
        if (v === null || v === "" || (k === "mode" && v === "dependency")) next.delete(k);
        else next.set(k, v);
      }
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [params, router, pathname],
  );

  // ---- the model -----------------------------------------------------------------------------------------------
  const moduleIndex = useMemo(() => buildModuleIndex(flattenTreeFiles(tree.data?.root).map((f) => f.path).filter(isParsedSourceFile)), [tree.data]);
  const allSymbols = useMemo(() => symbols.data?.symbols ?? [], [symbols.data]);
  const symbolNames = useMemo(() => new Set(allSymbols.map((s) => s.qualified_name)), [allSymbols]);
  // Whether a node is really part of the project (as opposed to a library it imports) is known only once the file tree
  // (or, for calls, the symbols) has loaded; building earlier would flash everything as "outside".
  const classifierReady = mode === "dependency" ? !tree.isLoading : !symbols.isLoading;
  const data = useMemo(() => {
    if (!active.data || !classifierReady) return null;
    const known = mode === "dependency" ? (tree.data ? moduleIndex : null) : symbols.data ? symbolNames : null;
    return buildGraphData(active.data, { isInternal: known ? (id) => known.has(id) : undefined });
  }, [active.data, classifierReady, mode, tree.data, moduleIndex, symbols.data, symbolNames]);
  const tangles = useMemo(() => (data && mode === "dependency" ? findTangles(data) : []), [data, mode]);
  const tangleOf = useMemo(() => tangleIndex(tangles), [tangles]);
  const hotspots = useMemo(
    () => new Set(mode === "dependency" ? (intelligence.data?.dependency_hotspots ?? []).slice(0, 5).map((h) => h.module_path) : []),
    [intelligence.data, mode],
  );
  const entryModules = useMemo(() => {
    if (!data || mode !== "dependency") return [];
    const seen = new Set<string>();
    for (const p of intelligence.data?.entry_points ?? []) {
      const id = data.byId.has(p) ? p : fileToModule(p);
      if (data.byId.has(id)) seen.add(id);
    }
    return [...seen].sort().map((id) => data.byId.get(id)!);
  }, [data, mode, intelligence.data]);
  const entries = useMemo(() => new Set(entryModules.map((m) => m.id)), [entryModules]);

  // ---- what is shown -------------------------------------------------------------------------------------------
  const [showTests, setShowTests] = useState(false);
  const [showExternal, setShowExternal] = useState(false);
  const [forced, setForced] = useState<ReadonlySet<ModuleKind>>(new Set());
  const kinds = useMemo(() => {
    const s = new Set<ModuleKind>(["source", ...forced]);
    if (showTests) {
      s.add("test");
      s.add("example");
    }
    if (showExternal) s.add("external");
    return s;
  }, [showTests, showExternal, forced]);

  // Open folders and per-folder limits belong to one graph; a different repository or graph type starts again.
  const graphKey = `${repositoryId}:${mode}`;
  const initialFocus = useRef(focus);
  // Modules that must be drawn even if a folder's cap would fold them away. Plain clicks on the map need no pin (what is
  // clicked is already drawn), so selecting never changes the picture and never triggers a new layout.
  const [pins, setPins] = useState<ReadonlySet<string>>(() => new Set(initialFocus.current ? [initialFocus.current] : []));
  const suggested = useMemo(() => {
    if (!data) return new Set<string>();
    const open = suggestExpansion(data, new Set<ModuleKind>(["source"]));
    if (initialFocus.current && data.byId.has(initialFocus.current)) for (const g of groupsToReveal(data, initialFocus.current)) open.add(g);
    return open;
  }, [data]);
  const [custom, setCustom] = useState<{ key: string; data: unknown; expanded: Set<string>; limits: Map<string, number> } | null>(null);
  const mine = custom && custom.key === graphKey && custom.data === data ? custom : null;
  const expanded = mine?.expanded ?? suggested;
  const limits = useMemo(() => mine?.limits ?? new Map<string, number>(), [mine]);
  const [resets, setResets] = useState(0);

  const [edgesOverride, setEdgesOverride] = useState<EdgeMode | null>(null);
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [reveal, setReveal] = useState<{ moduleId: string; n: number } | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [summaryOpen, setSummaryOpen] = useState(false);

  const selected = focus && data?.byId.has(focus) ? focus : null;
  const selectedInfo = selected && data ? data.byId.get(selected)! : null;
  const viewKinds = useMemo(() => (selectedInfo && !kinds.has(selectedInfo.kind) ? new Set([...kinds, selectedInfo.kind]) : kinds), [kinds, selectedInfo]);
  const pinned = pins;
  const fullView = useMemo(
    () => (data ? buildView(data, { expanded, kinds: viewKinds, limits, pinned, hideUnconnected: true }, tangleOf) : null),
    [data, expanded, viewKinds, limits, pinned, tangleOf],
  );
  // With more than a few dozen arrows the arrows into shared modules bury everything else, so they start hidden.
  const edgeMode: EdgeMode = edgesOverride ?? ((fullView?.edges.length ?? 0) > 40 ? "key" : "all");
  const view = useMemo(
    () => (data && fullView ? (edgeMode === "key" ? buildView(data, { expanded, kinds: viewKinds, limits, pinned, hideUnconnected: true, hideHubEdges: true }, tangleOf) : fullView) : null),
    [data, fullView, edgeMode, expanded, viewKinds, limits, pinned, tangleOf],
  );
  // Re-arranging is the expensive step, so it only runs when what is drawn (not how it is highlighted) has changed.
  const lastShape = useRef<{ sig: string; view: GraphView } | null>(null);
  const layoutView = useMemo(() => {
    if (!view) return null;
    const sig =
      view.nodes.map((n) => (n.kind === "group" ? `${n.id}${n.expanded ? "+" : "-"}${n.moduleCount}` : n.kind === "more" ? `${n.id}:${n.hidden}` : n.id)).join("|") +
      "#" +
      view.edges.map((e) => e.id).join("|");
    if (lastShape.current?.sig === sig) return lastShape.current.view;
    lastShape.current = { sig, view };
    return view;
  }, [view]);
  const layout = useGraphLayout(layoutMode === "map" ? layoutView : null);

  function commit(nextExpanded: Set<string>, nextLimits: Map<string, number>): boolean {
    if (!data) return false;
    const probe = buildView(data, { expanded: nextExpanded, kinds: viewKinds, limits: nextLimits, pinned, hideUnconnected: true });
    if (probe.nodes.length > MAX_DRAWN) {
      setNote(`That would draw ${probe.nodes.length.toLocaleString("en-US")} boxes at once, which is too many to read. Open a smaller folder, or use the list.`);
      return false;
    }
    setNote(null);
    setCustom({ key: graphKey, data, expanded: nextExpanded, limits: nextLimits });
    return true;
  }
  const toggleGroup = (groupId: string) => {
    const next = new Set(expanded);
    if (next.has(groupId)) next.delete(groupId);
    else next.add(groupId);
    commit(next, new Map(limits));
  };
  const showMore = (groupId: string) => {
    const next = new Map(limits);
    next.set(groupId, (next.get(groupId) ?? DEFAULT_GROUP_LIMIT) + DEFAULT_GROUP_LIMIT * 2);
    commit(new Set(expanded), next);
  };
  const resetView = () => {
    setCustom(null);
    setNote(null);
    setEdgesOverride(null);
    setForced(new Set());
    setPins(new Set());
    setResets((n) => n + 1);
    setParams({ focus: null });
  };

  /** Select a module wherever it is: opens the folders around it, shows its kind if hidden, and brings it into view. */
  const pick = (id: string) => {
    if (!data) return;
    const info = data.byId.get(id);
    if (!info) return;
    if (!kinds.has(info.kind)) setForced((f) => new Set([...f, info.kind]));
    const next = new Set(expanded);
    for (const g of groupsToReveal(data, id)) next.add(g);
    setCustom({ key: graphKey, data, expanded: next, limits: new Map(limits) });
    setPins((p) => new Set([...p, id]));
    setNote(null);
    setParams({ focus: id });
    setReveal((r) => ({ moduleId: id, n: (r?.n ?? 0) + 1 }));
    setSearchOpen(false);
  };
  const select = (id: string | null) => setParams({ focus: id });

  // ---- search --------------------------------------------------------------------------------------------------
  const results = useMemo(() => (data && query.trim() ? searchModules(data, query, ALL_KINDS, 8) : []), [data, query]);
  const [cursor, setCursor] = useState(0);
  useEffect(() => setCursor(0), [query]);

  // ---- inspector data ------------------------------------------------------------------------------------------
  const focusFile = selected ? (mode === "dependency" ? moduleIndex.get(selected) ?? null : allSymbols.find((s) => s.qualified_name === selected)?.file_path ?? null) : null;
  const focusSymbols = useMemo(() => {
    if (!selected) return [];
    if (mode === "call") {
      const sym = allSymbols.find((s) => s.qualified_name === selected);
      return sym ? [sym, ...allSymbols.filter((s) => s.parent_symbol_id === sym.id)] : [];
    }
    return focusFile ? allSymbols.filter((s) => s.file_path === focusFile) : [];
  }, [selected, mode, allSymbols, focusFile]);

  const hiddenCounts = useMemo(() => {
    if (!data) return { tests: 0, external: 0 };
    let tests = 0;
    let external = 0;
    for (const m of data.modules) {
      if ((m.kind === "test" || m.kind === "example") && !kinds.has(m.kind)) tests++;
      if (m.kind === "external" && !kinds.has("external")) external++;
    }
    return { tests, external };
  }, [data, kinds]);

  const panel = !data ? null : selectedInfo ? (
    <ModuleInspector
      kind={mode}
      data={data}
      module={selectedInfo}
      file={focusFile}
      symbols={focusSymbols}
      tangle={tangleOf.has(selectedInfo.id) ? tangles[tangleOf.get(selectedInfo.id)!] : null}
      isHotspot={hotspots.has(selectedInfo.id)}
      isEntry={entries.has(selectedInfo.id)}
      repositoryId={repositoryId}
      onPick={pick}
      onClose={() => select(null)}
    />
  ) : (
    <GraphSummary
      kind={mode}
      data={data}
      kinds={kinds}
      tangles={tangles}
      entries={entryModules}
      unconnected={view?.unconnected ?? 0}
      hidden={hiddenCounts}
      onPick={pick}
      onShowList={() => {
        setParams({ view: "list" });
        setSummaryOpen(false);
      }}
    />
  );

  const loading = active.isLoading || !classifierReady;
  const drawn = layout.view && layout.result ? { view: layout.view, result: layout.result } : null;
  const compact = breakpoint !== "desktop";

  return (
    <div className="grid h-full min-h-0 grid-cols-1 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div className="flex min-h-0 min-w-0 flex-col">
        <div className="flex flex-wrap items-center gap-x-[18px] gap-y-3 border-b border-border-subtle px-4 py-3.5 sm:px-6">
          <h1 className="font-display text-[24px] font-semibold tracking-[-0.015em] text-text-primary sm:text-[26px]">Knowledge map</h1>
          <SegmentedControl
            aria-label="Graph type"
            value={mode}
            onChange={(v) => setParams({ mode: v, focus: null })}
            options={[
              { value: "dependency", label: "Dependencies" },
              { value: "call", label: "Call graph" },
            ]}
          />
          <SegmentedControl
            aria-label="Layout"
            value={layoutMode}
            onChange={(v) => setParams({ view: v })}
            options={[
              { value: "map", label: "Map" },
              { value: "list", label: "List" },
            ]}
          />
          <span className="flex-1" />
          {layoutMode === "map" && (
            <button className="cs-chipbtn" onClick={resetView} title="Back to the starting view">
              <RotateCcw size={12} aria-hidden="true" /> Reset view
            </button>
          )}
          {compact && (
            <button onClick={() => setSummaryOpen(true)} className="cs-chipbtn">
              <ListTree size={13} aria-hidden="true" /> Summary
            </button>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2 border-b border-border-subtle px-4 py-2.5 sm:px-6">
          <div className="relative w-full sm:w-[280px]">
            <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-tertiary" aria-hidden="true" />
            <input
              role="combobox"
              aria-expanded={searchOpen && results.length > 0}
              aria-controls="graph-search-results"
              aria-autocomplete="list"
              aria-label={`Find a ${words.unit}`}
              value={query}
              placeholder={`Find a ${words.unit}…`}
              onChange={(e) => {
                setQuery(e.target.value);
                setSearchOpen(true);
              }}
              onFocus={() => setSearchOpen(true)}
              onBlur={() => setTimeout(() => setSearchOpen(false), 120)}
              onKeyDown={(e) => {
                if (layoutMode === "list") return;
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setCursor((c) => Math.min(results.length - 1, c + 1));
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setCursor((c) => Math.max(0, c - 1));
                } else if (e.key === "Enter" && results[cursor]) {
                  e.preventDefault();
                  pick(results[cursor].id);
                } else if (e.key === "Escape") setSearchOpen(false);
              }}
              className="h-9 w-full rounded-md border border-border-subtle bg-surface-1 pl-9 pr-8 text-[13px] text-text-primary outline-none placeholder:text-text-tertiary focus-visible:border-violet focus-visible:ring-2 focus-visible:ring-violet/30"
            />
            {query && (
              <button onClick={() => setQuery("")} aria-label="Clear search" className="absolute right-1.5 top-1/2 grid h-6 w-6 -translate-y-1/2 place-items-center rounded text-text-tertiary hover:text-text-primary">
                <X size={13} aria-hidden="true" />
              </button>
            )}
            {layoutMode === "map" && searchOpen && results.length > 0 && (
              <ul id="graph-search-results" role="listbox" className="absolute left-0 top-full z-30 mt-1 w-full overflow-hidden rounded-md border border-border-strong bg-surface-1 shadow-lg">
                {results.map((m, i) => (
                  <li key={m.id} role="option" aria-selected={i === cursor}>
                    <button
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => pick(m.id)}
                      className={cn("flex w-full items-baseline gap-2 px-3 py-2 text-left hover:bg-surface-2", i === cursor && "bg-surface-2")}
                    >
                      <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-text-primary">{m.id}</span>
                      {m.kind !== "source" && <span className="flex-none text-[10.5px] text-text-tertiary">{m.kind === "external" ? "outside" : m.kind}</span>}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <button className="cs-chipbtn" aria-pressed={showTests} onClick={() => setShowTests(!showTests)}>
            Tests &amp; examples
          </button>
          <button className="cs-chipbtn" aria-pressed={showExternal} onClick={() => setShowExternal(!showExternal)}>
            Outside packages
          </button>
          {layoutMode === "map" && (
            <>
              <span className="mx-1 hidden h-5 w-px bg-border-subtle sm:block" aria-hidden="true" />
              <SegmentedControl
                aria-label="Which arrows to draw"
                value={edgeMode}
                onChange={(v) => setEdgesOverride(v)}
                options={[
                  { value: "key", label: "Key arrows" },
                  { value: "all", label: "All arrows" },
                  { value: "selected", label: "Selected" },
                ]}
              />
            </>
          )}
        </div>

        {layoutMode === "map" && view && edgeMode === "key" && view.hubs.length > 0 && (
          <p className="border-b border-border-subtle bg-surface-1 px-4 py-2 text-[12px] text-text-secondary sm:px-6">
            Arrows into <b className="font-medium text-text-primary">{view.hubs.length} shared {view.hubs.length === 1 ? words.unit : words.units}</b> ({view.hubs.slice(0, 3).map((h) => data?.byId.get(h)?.label).join(", ")}
            {view.hubs.length > 3 ? "…" : ""}) are hidden: nearly everything uses them. Select one to see them.
          </p>
        )}
        {layoutMode === "map" && mode === "call" && view && view.nodes.length > 0 && view.edges.length === 0 && (
          <p className="border-b border-border-subtle bg-surface-1 px-4 py-2 text-[12px] text-text-secondary sm:px-6">
            Calls are only resolved inside a single file, so closed folders show no arrows between them. Open a folder to see which functions call which.
          </p>
        )}
        <div className="relative min-h-[360px] flex-1">
          {loading && <div className="cs-skel absolute inset-8" />}
          {active.isError && (
            <div className="p-8">
              <ErrorPanel error={active.error} onRetry={() => active.refetch()} />
            </div>
          )}
          {data && view && view.nodes.length === 0 && layoutMode === "map" && (
            <div className="grid h-full place-items-center px-6 text-center">
              <div className="flex max-w-sm flex-col items-center gap-3">
                <TopologyMark variant="mark" size={36} />
                <p className="text-text-secondary">
                  {data.modules.length === 0
                    ? "No relationships were found for this graph type yet."
                    : `Nothing to draw with the current filters. ${view.unconnected.toLocaleString("en-US")} standalone ${words.units} have no connections; switch to List to browse them.`}
                </p>
              </div>
            </div>
          )}
          {data && layoutMode === "map" && drawn && view && view.nodes.length > 0 && (
            <GraphCanvas
              data={data}
              view={drawn.view}
              layout={drawn.result}
              tangleOf={mode === "dependency" ? tangleOf : NO_TANGLES}
              hotspots={hotspots}
              entries={entries}
              loopMarks={selectedInfo !== null && tangleOf.has(selectedInfo.id) && tangles[tangleOf.get(selectedInfo.id)!].members.length <= LOOP_MARK_LIMIT}
              selected={selected}
              edgeMode={edgeMode}
              onSelect={select}
              onToggleGroup={toggleGroup}
              onShowMore={showMore}
              fitKey={`${graphKey}:${resets}`}
              reveal={reveal}
            />
          )}
          {layoutMode === "map" && layout.status === "working" && drawn && (
            <span className="pointer-events-none absolute right-4 top-3 rounded-full border border-border-subtle bg-surface-1 px-2.5 py-1 text-[11px] text-text-tertiary" role="status">
              Arranging…
            </span>
          )}
          {layout.status === "error" && !drawn && (
            <div className="p-8">
              <ErrorPanel error={new Error(layout.error ?? "The map could not be laid out.")} onRetry={resetView} />
            </div>
          )}
          {data && layoutMode === "list" && (
            <ModuleTable data={data} kinds={kinds} query={query} selected={selected} tangleOf={mode === "dependency" ? tangleOf : NO_TANGLES} hotspots={hotspots} entries={entries} unit={words.unit} onSelect={(id) => select(id === selected ? null : id)} />
          )}
          {note && (
            <p role="status" className="absolute inset-x-4 top-3 z-20 mx-auto max-w-lg rounded-md border border-border-strong bg-surface-1 px-3.5 py-2.5 text-[12.5px] text-text-secondary shadow-lg">
              {note}
            </p>
          )}
          <p className="sr-only" role="status">
            {view ? `Map: ${view.nodes.length} boxes and ${view.edges.length} arrows drawn from ${view.includedModules} ${words.units}.${selected ? ` Selected ${selected}.` : ""}` : "Loading the map."}
          </p>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t border-border-subtle px-4 py-2.5 sm:px-6">
          {layoutMode === "map" ? <GraphKey kind={mode} hasTangles={tangles.length > 0} /> : <span className="text-[12px] text-text-tertiary">Select a row for details.</span>}
          {data && view && (
            <span className="cs-monoline !text-[11px]">
              {view.includedModules.toLocaleString("en-US")} of {data.modules.length.toLocaleString("en-US")} {words.units} · {data.edges.length.toLocaleString("en-US")} {words.edge}s in total
            </span>
          )}
        </div>
      </div>

      <aside aria-label="Details" aria-live="polite" className="cs-scrollbar hidden min-h-0 overflow-y-auto border-l border-border-subtle bg-surface-1 px-[22px] pb-10 pt-6 xl:block">
        {panel}
      </aside>
      {compact && (
        <>
          <Modal open={Boolean(selected)} onOpenChange={(o) => !o && select(null)} title="Details" side="right">
            {selectedInfo ? panel : null}
          </Modal>
          <Modal open={summaryOpen && !selected} onOpenChange={setSummaryOpen} title="Summary" side="right">
            {panel}
          </Modal>
        </>
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
