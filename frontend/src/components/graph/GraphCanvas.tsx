"use client";

import "@xyflow/react/dist/style.css";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Background, Controls, MarkerType, MiniMap, ReactFlow, type Edge, type Node, type ReactFlowInstance } from "@xyflow/react";
import { CsGraphEdge, CsGraphNode, NODE_WIDTH, type CsGraphEdgeData, type CsGraphNodeData } from "@/components/graph/GraphNode";
import { forceLayout, nodeRadius } from "@/lib/forceLayout";
import { edgeKey, neighborsOf, nodeLabel, sharedPrefixDepth, type GraphModel } from "@/lib/graphModel";

const nodeTypes = { cs: CsGraphNode };
const edgeTypes = { cs: CsGraphEdge };
const W = 1200;
const H = 860;

/**
 * Interactive knowledge map (React Flow). Positions come from the
 * deterministic force layout over the capped model; selection, hover
 * neighbourhood highlighting and arrow-key neighbour navigation are all
 * driven from here.
 */
export function GraphCanvas({
  model,
  mode,
  hotspots,
  orphans,
  cycleKeys,
  selected,
  onSelect,
  layoutKey,
}: {
  model: GraphModel;
  mode: "dependency" | "call";
  hotspots: Set<string>;
  orphans: Set<string>;
  cycleKeys: Set<string>;
  selected: string | null;
  onSelect: (id: string | null) => void;
  layoutKey: string;
}) {
  const [hover, setHover] = useState<string | null>(null);
  const flow = useRef<ReactFlowInstance | null>(null);
  const positions = useMemo(() => forceLayout(model.nodes, model.edges, { width: W, height: H, iterations: 420, key: layoutKey }), [model, layoutKey]);
  const pos = useMemo(() => new Map(model.nodes.map((n, i) => [n, positions[i]])), [model.nodes, positions]);
  const maxDegree = Math.max(1, ...model.nodes.map((n) => model.degree.get(n) ?? 0));
  const radius = useCallback((n: string) => nodeRadius(model.degree.get(n) ?? 0, maxDegree), [model, maxDegree]);
  const prefixDepth = useMemo(() => sharedPrefixDepth(model.nodes), [model.nodes]);
  const focus = hover ?? selected;
  const near = useMemo(() => (focus ? neighborsOf(model.edges, focus) : null), [focus, model.edges]);
  const activate = useCallback((id: string) => onSelect(id === selected ? null : id), [onSelect, selected]);

  const nodes: Node<CsGraphNodeData>[] = useMemo(
    () =>
      model.nodes.map((n) => {
        const p = pos.get(n)!;
        const r = radius(n);
        return {
          id: n,
          type: "cs",
          position: { x: p.x - NODE_WIDTH / 2, y: p.y - r - 10 },
          width: NODE_WIDTH,
          height: r * 2 + 34,
          draggable: false,
          selectable: false,
          focusable: false,
          data: {
            id: n,
            label: nodeLabel(n, mode, prefixDepth),
            radius: r,
            inDegree: model.inDegree.get(n) ?? 0,
            outDegree: model.outDegree.get(n) ?? 0,
            hotspot: mode === "dependency" && hotspots.has(n),
            orphan: mode === "dependency" && orphans.has(n),
            selected: n === selected,
            dim: Boolean(focus && n !== focus && !near?.has(n)),
            hub: (model.degree.get(n) ?? 0) >= maxDegree * 0.45,
            onActivate: activate,
            onHover: setHover,
          },
        };
      }),
    [model, pos, radius, mode, prefixDepth, hotspots, orphans, selected, focus, near, maxDegree, activate],
  );

  const edges: Edge<CsGraphEdgeData>[] = useMemo(() => {
    const keys = new Set(model.edges.map(edgeKey));
    return model.edges.map((e) => {
      const cycle = mode === "dependency" && cycleKeys.has(edgeKey(e));
      const active = Boolean(focus && (e.source === focus || e.target === focus));
      const color = cycle ? "var(--cs-danger)" : active ? "var(--cs-accent-violet)" : "oklch(1 0 0 / 0.32)";
      return {
        id: edgeKey(e),
        source: e.source,
        target: e.target,
        type: "cs",
        focusable: false,
        selectable: false,
        markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color },
        data: {
          sourceRadius: radius(e.source),
          targetRadius: radius(e.target),
          cycle,
          active,
          dim: Boolean(focus && !active),
          bend: keys.has(`${e.target}→${e.source}`) ? 26 : 0,
        },
      };
    });
  }, [model.edges, mode, cycleKeys, focus, radius]);

  // Frame the selected node together with its direct neighbours, so the
  // relationships the inspector lists are on screen (sparse graphs would
  // otherwise push them out of view at a fixed zoom).
  const frame = useCallback(
    (inst: ReactFlowInstance, node: string, duration: number) => {
      const ids = [node, ...neighborsOf(model.edges, node)].map((id) => ({ id }));
      inst.fitView({ nodes: ids, padding: 0.35, maxZoom: 1.2, duration });
    },
    [model.edges],
  );
  useEffect(() => {
    if (!selected || !flow.current || !pos.has(selected)) return;
    frame(flow.current, selected, 280);
  }, [selected, pos, frame]);

  function onKeyDown(e: React.KeyboardEvent) {
    const dir: Record<string, [number, number]> = { ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0] };
    if (e.key === "Escape") {
      onSelect(null);
      return;
    }
    const v = dir[e.key];
    if (!v) return;
    const current = (e.target as HTMLElement).closest<HTMLElement>("[data-graph-node]")?.dataset.graphNode;
    if (!current) return;
    e.preventDefault();
    const a = pos.get(current)!;
    const candidates = [...(neighborsOf(model.edges, current).size ? neighborsOf(model.edges, current) : new Set(model.nodes.filter((n) => n !== current)))];
    let best: string | null = null;
    let bestScore = Infinity;
    for (const c of candidates) {
      const b = pos.get(c)!;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const along = dx * v[0] + dy * v[1];
      if (along <= 0) continue;
      const score = along + Math.abs(dx * v[1] - dy * v[0]) * 2.2;
      if (score < bestScore) {
        bestScore = score;
        best = c;
      }
    }
    if (best) {
      document.querySelector<HTMLElement>(`[data-graph-node="${CSS.escape(best)}"]`)?.focus();
      onSelect(best);
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
          if (selected && pos.has(selected)) requestAnimationFrame(() => frame(inst as unknown as ReactFlowInstance, selected, 0));
        }}
        onNodeClick={(_e, node) => activate(node.id)}
        onPaneClick={() => onSelect(null)}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        nodesFocusable={false}
        edgesFocusable={false}
        fitView
        fitViewOptions={{ padding: 0.12 }}
        minZoom={0.25}
        maxZoom={2.5}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="oklch(1 0 0 / 0.055)" gap={24} size={1.2} />
        <Controls showInteractive={false} position="bottom-left" />
        <MiniMap
          pannable
          zoomable
          position="bottom-right"
          nodeColor={(n) => ((n.data as CsGraphNodeData).hotspot ? "oklch(0.75 0.13 300)" : "oklch(1 0 0 / 0.45)")}
          nodeStrokeWidth={0}
          maskColor="oklch(0.1 0.006 280 / 0.6)"
          style={{ background: "oklch(0.18 0.009 280 / 0.85)", width: 170, height: 120 }}
        />
      </ReactFlow>
    </div>
  );
}
