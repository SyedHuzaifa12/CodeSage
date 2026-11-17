"use client";

import "@xyflow/react/dist/style.css";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { Background, Controls, MarkerType, MiniMap, ReactFlow, type Edge, type Node, type ReactFlowInstance } from "@xyflow/react";
import {
  AggregateEdge,
  GroupNode,
  MoreNode,
  ModuleNode,
  type AggregateEdgeData,
  type GroupNodeData,
  type MoreNodeData,
  type ModuleNodeData,
  type Relation,
} from "@/components/graph/GraphNode";
import type { LayoutResult } from "@/lib/graph/layout";
import { moduleViewId, type GraphData, type GraphView } from "@/lib/graph/model";

// Declared once at module scope: React Flow re-creates every node if these objects change identity between renders.
// "group" is avoided on purpose: React Flow gives that exact type name its own default border and background.
const nodeTypes = { module: ModuleNode, folder: GroupNode, more: MoreNode };
const edgeTypes = { aggregate: AggregateEdge };

/** key: arrows into shared hub modules are left out until one end is selected; all: every arrow; selected: only the selection's. */
export type EdgeMode = "key" | "all" | "selected";

export interface GraphCanvasProps {
  data: GraphData;
  view: GraphView;
  layout: LayoutResult;
  /** module id -> index of the circular-dependency knot it is part of. */
  tangleOf: ReadonlyMap<string, number>;
  hotspots: ReadonlySet<string>;
  entries: ReadonlySet<string>;
  /** Draw the selected module's loop (marks and red dashes). Off for a huge loop, where it would mark most of the map. */
  loopMarks: boolean;
  selected: string | null;
  edgeMode: EdgeMode;
  onSelect: (moduleId: string | null) => void;
  onToggleGroup: (groupId: string) => void;
  onShowMore: (groupId: string) => void;
  /** Changing this re-frames the whole picture (a new repository or graph type). */
  fitKey: string;
  /** Asks the canvas to bring one module into view (a search result, a click in the inspector). */
  reveal: { moduleId: string; n: number } | null;
}

/** Offset of a node from the top-left of the whole picture (layout positions are relative to the parent box). */
function absolutePositions(view: GraphView, layout: LayoutResult) {
  const parent = new Map(view.nodes.map((n) => [n.id, n.parent]));
  const out = new Map<string, { x: number; y: number; width: number; height: number }>();
  const resolve = (id: string): { x: number; y: number; width: number; height: number } | null => {
    const hit = out.get(id);
    if (hit) return hit;
    const p = layout.positions[id];
    if (!p) return null;
    const par = parent.get(id);
    const base = par ? resolve(par) : { x: 0, y: 0 };
    if (!base) return null;
    const abs = { x: base.x + p.x, y: base.y + p.y, width: p.width, height: p.height };
    out.set(id, abs);
    return abs;
  };
  for (const n of view.nodes) resolve(n.id);
  return out;
}

export function GraphCanvas({ data, view, layout, tangleOf, hotspots, entries, loopMarks, selected, edgeMode, onSelect, onToggleGroup, onShowMore, fitKey, reveal }: GraphCanvasProps) {
  const flow = useRef<ReactFlowInstance | null>(null);
  const lastFit = useRef<string | null>(null);
  const lastReveal = useRef<number>(0);

  const abs = useMemo(() => absolutePositions(view, layout), [view, layout]);
  const selectedId = selected ? moduleViewId(selected) : null;
  const drawn = useMemo(() => new Set(view.nodes.map((n) => n.id)), [view.nodes]);
  const selectedDrawn = selectedId !== null && drawn.has(selectedId);

  // Everything the selection touches, and which way: it imports them ("imports") or they import it ("importedBy").
  const relation = useMemo(() => {
    const m = new Map<string, Relation>();
    if (!selectedDrawn) return m;
    for (const e of [...view.edges, ...view.hubEdges]) {
      if (e.source === selectedId) m.set(e.target, "imports");
      else if (e.target === selectedId) m.set(e.source, "importedBy");
    }
    return m;
  }, [view.edges, view.hubEdges, selectedId, selectedDrawn]);

  const ancestors = useMemo(() => {
    const set = new Set<string>();
    if (!selectedDrawn) return set;
    const parent = new Map(view.nodes.map((n) => [n.id, n.parent]));
    for (let p = parent.get(selectedId!); p; p = parent.get(p)) set.add(p);
    return set;
  }, [view.nodes, selectedId, selectedDrawn]);

  const selectedTangle = loopMarks && selected ? tangleOf.get(selected) ?? null : null;
  const nodes: Node[] = useMemo(() => {
    const focusing = selectedDrawn;
    return view.nodes.flatMap((n): Node[] => {
      const p = layout.positions[n.id];
      if (!p) return [];
      const base = { id: n.id, position: { x: p.x, y: p.y }, width: p.width, height: p.height, parentId: n.parent ?? undefined, draggable: false, selectable: false, focusable: false };
      if (n.kind === "group") {
        const related = relation.has(n.id) || ancestors.has(n.id) || n.id === selectedId;
        const data: GroupNodeData = { groupId: n.groupId, label: n.label, expanded: n.expanded, moduleCount: n.moduleCount, dim: focusing && !n.expanded && !related, onToggle: onToggleGroup };
        return [{ ...base, type: "folder", data }];
      }
      if (n.kind === "more") {
        const data: MoreNodeData = { groupId: n.groupId, hidden: n.hidden, dim: focusing && !relation.has(n.id), onMore: onShowMore };
        return [{ ...base, type: "more", data }];
      }
      const m = data.byId.get(n.moduleId)!;
      const data2: ModuleNodeData = {
        moduleId: m.id,
        label: n.label,
        kind: m.kind,
        usedBy: m.inDegree,
        hotspot: hotspots.has(m.id),
        entry: entries.has(m.id),
        // Loop markers appear only on the members of the loop the selected module is in; on a codebase where most
        // modules are tangled, marking all of them would say nothing.
        tangled: selectedTangle !== null && tangleOf.get(m.id) === selectedTangle,
        selected: n.id === selectedId,
        relation: relation.get(n.id) ?? null,
        dim: focusing && n.id !== selectedId && !relation.has(n.id),
        onSelect: (id) => onSelect(id === selected ? null : id),
      };
      return [{ ...base, type: "module", data: data2 }];
    });
  }, [view.nodes, layout.positions, data.byId, hotspots, entries, tangleOf, selectedTangle, selectedId, selectedDrawn, selected, relation, ancestors, onSelect, onToggleGroup, onShowMore]);

  const edges: Edge[] = useMemo(() => {
    const showCount = view.edges.length <= 40;
    const touches = (e: { source: string; target: string }) => selectedDrawn && (e.source === selectedId || e.target === selectedId);
    // Hidden hub arrows come back for the selected module, so its full set of connections is always on screen.
    const list = edgeMode === "key" ? [...view.edges, ...view.hubEdges.filter(touches)] : view.edges;
    return list.flatMap((e): Edge[] => {
      const direction: AggregateEdgeData["direction"] = !selectedDrawn ? null : e.source === selectedId ? "out" : e.target === selectedId ? "in" : null;
      if (edgeMode === "selected" && direction === null) return [];
      // A loop is only drawn as one when the selected module is part of it: in a codebase where dozens of modules are
      // tangled, marking every arrow red would mark nearly all of them and say nothing.
      const loop = e.tangle !== null && e.tangle === selectedTangle;
      const color = loop ? "var(--cs-danger)" : direction === "in" ? "var(--cs-accent-cyan)" : direction === "out" ? "var(--cs-accent-violet)" : "oklch(var(--cs-ov) 0 0 / 0.34)";
      const data: AggregateEdgeData = { weight: e.weight, tangled: loop, direction, dim: selectedDrawn && direction === null, showCount };
      return [
        {
          id: e.id,
          source: e.source,
          target: e.target,
          type: "aggregate",
          focusable: false,
          selectable: false,
          markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color },
          data,
        },
      ];
    });
  }, [view.edges, view.hubEdges, selectedId, selectedDrawn, selectedTangle, edgeMode]);

  const fit = useCallback((duration: number) => flow.current?.fitView({ padding: 0.1, maxZoom: 1.1, duration }), []);

  // Re-frame when the picture is a different one (not on every expand: a viewport that jumps while you are reading is
  // disorienting). The layout arrives asynchronously, so this waits for positions that match the current view.
  useEffect(() => {
    if (!flow.current || lastFit.current === fitKey) return;
    lastFit.current = fitKey;
    requestAnimationFrame(() => fit(0));
  }, [fitKey, layout, fit]);

  useEffect(() => {
    if (!reveal || reveal.n === lastReveal.current || !flow.current) return;
    const box = abs.get(moduleViewId(reveal.moduleId));
    if (!box) return;
    lastReveal.current = reveal.n;
    const zoom = Math.max(flow.current.getZoom(), 0.9);
    requestAnimationFrame(() => flow.current?.setCenter(box.x + box.width / 2, box.y + box.height / 2, { zoom, duration: 300 }));
  }, [reveal, abs]);

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      onSelect(null);
      return;
    }
    if (!["ArrowRight", "ArrowLeft", "ArrowUp", "ArrowDown"].includes(e.key)) return;
    const current = (e.target as HTMLElement).closest<HTMLElement>("[data-graph-node]")?.dataset.graphNode;
    if (!current) return;
    const from = moduleViewId(current);
    const here = abs.get(from);
    if (!here) return;
    e.preventDefault();
    // Down follows an import to what it imports; up goes back to what imports it; left and right move along the row.
    let pool: string[];
    if (e.key === "ArrowDown") pool = view.edges.filter((x) => x.source === from).map((x) => x.target);
    else if (e.key === "ArrowUp") pool = view.edges.filter((x) => x.target === from).map((x) => x.source);
    else pool = view.nodes.filter((n) => n.kind === "module" && n.id !== from && Math.abs((abs.get(n.id)?.y ?? 1e9) - here.y) < here.height).map((n) => n.id);
    let best: string | null = null;
    let bestScore = Infinity;
    for (const id of pool) {
      const b = abs.get(id);
      if (!b || !id.startsWith("m:")) continue;
      const dx = b.x - here.x;
      if (e.key === "ArrowLeft" && dx >= 0) continue;
      if (e.key === "ArrowRight" && dx <= 0) continue;
      const score = e.key === "ArrowLeft" || e.key === "ArrowRight" ? Math.abs(dx) : Math.abs(dx) + Math.abs(b.y - here.y) * 0.2;
      if (score < bestScore) {
        bestScore = score;
        best = id;
      }
    }
    if (best) {
      const id = best.slice(2);
      document.querySelector<HTMLElement>(`[data-graph-node="${CSS.escape(id)}"]`)?.focus();
      onSelect(id);
    }
  }

  return (
    <div className="cs-graph-canvas relative h-full w-full" onKeyDown={onKeyDown}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onInit={(inst) => {
          flow.current = inst as unknown as ReactFlowInstance;
        }}
        onPaneClick={() => onSelect(null)}
        // The boxes handle their own clicks. React Flow switches pointer events off for nodes that are neither selectable,
        // draggable nor given a click handler, so a no-op handler is what keeps the buttons inside them clickable.
        onNodeClick={() => undefined}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        nodesFocusable={false}
        edgesFocusable={false}
        onlyRenderVisibleElements={nodes.length > 160}
        fitView
        fitViewOptions={{ padding: 0.1, maxZoom: 1.1 }}
        minZoom={0.1}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
        aria-label="Dependency map"
      >
        <Background color="oklch(var(--cs-ov) 0 0 / 0.07)" gap={24} size={1.2} />
        <Controls showInteractive={false} position="bottom-left" />
        <MiniMap
          pannable
          zoomable
          position="bottom-right"
          ariaLabel="Overview of the whole map"
          nodeColor={(n) => (n.type === "folder" ? "oklch(var(--cs-ov) 0 0 / 0.12)" : "oklch(var(--cs-ov) 0 0 / 0.42)")}
          nodeStrokeWidth={0}
          maskColor="var(--cs-minimap-mask)"
          style={{ background: "var(--cs-glass)", width: 150, height: 100 }}
        />
      </ReactFlow>
    </div>
  );
}
