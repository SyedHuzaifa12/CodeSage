"use client";

import "@xyflow/react/dist/style.css";
import { useMemo, useRef } from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import { CsGraphNode, type CsGraphNodeData } from "@/components/graph/GraphNode";
import { computeRadialLayout } from "@/lib/radialLayout";
import type { GraphEdge } from "@/lib/types/workspace";

const nodeTypes = { cs: CsGraphNode };

interface GraphCanvasProps {
  nodes: string[];
  edges: GraphEdge[];
  hotspotFiles: Set<string>;
  focusedNode: string | null;
  onNodeClick: (id: string) => void;
}

/**
 * The interactive Graph canvas (Design System §17/D): real pan/zoom
 * (@xyflow/react), centrality-sized nodes, a functional minimap, and
 * arrow-key neighbor navigation once a node has focus (§12) — not static
 * chrome, per the design doc's own explicit warning that an unwired
 * minimap/focus-vignette "would read as broken rather than premium."
 */
export function GraphCanvas({ nodes, edges, hotspotFiles, focusedNode, onNodeClick }: GraphCanvasProps) {
  const layout = useMemo(() => computeRadialLayout(nodes, edges, nodes.length), [nodes, edges]);
  const positionById = useRef(new Map<string, { x: number; y: number }>());
  const adjacency = useRef(new Map<string, string[]>());

  const { flowNodes, flowEdges } = useMemo(() => {
    const maxDegree = Math.max(1, ...layout.nodes.map((n) => n.degree));
    positionById.current = new Map(layout.nodes.map((n) => [n.id, { x: n.x, y: n.y }]));

    const adj = new Map<string, string[]>();
    for (const n of layout.nodes) adj.set(n.id, []);
    for (const e of layout.edges) {
      adj.get(e.source)?.push(e.target);
      adj.get(e.target)?.push(e.source);
    }
    adjacency.current = adj;

    const fNodes: Node<CsGraphNodeData>[] = layout.nodes.map((n) => {
      const ratio = maxDegree > 0 ? n.degree / maxDegree : 0;
      // Explicit width/height (matching CsGraphNode's actual rendered size)
      // rather than relying purely on React Flow's async ResizeObserver
      // measurement — the MiniMap needs concrete dimensions immediately to
      // draw each node's shape; without this it silently renders nothing.
      const nodeWidth = 10 + ratio * 22 + 60;
      const nodeHeight = 46;
      return {
        id: n.id,
        type: "cs",
        position: { x: n.x, y: n.y },
        width: nodeWidth,
        height: nodeHeight,
        data: {
          label: n.id.length > 28 ? `…${n.id.slice(-26)}` : n.id,
          degree: n.degree,
          maxDegree,
          isHotspot: hotspotFiles.has(n.id),
          focused: n.id === focusedNode,
        },
      };
    });

    const fEdges: Edge[] = layout.edges.map((e, i) => ({
      id: `e-${i}`,
      source: e.source,
      target: e.target,
      style: { stroke: "oklch(0.4 0.02 280)", strokeWidth: 1.4 },
      animated: false,
    }));

    return { flowNodes: fNodes, flowEdges: fEdges };
  }, [layout, hotspotFiles, focusedNode]);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key)) return;
    const target = e.target as HTMLElement;
    const wrapper = target.closest(".react-flow__node") as HTMLElement | null;
    const currentId = wrapper?.getAttribute("data-id");
    if (!currentId) return;

    const pos = positionById.current.get(currentId);
    const neighbors = adjacency.current.get(currentId) ?? [];
    if (!pos || neighbors.length === 0) return;

    const dir: Record<string, [number, number]> = {
      ArrowUp: [0, -1],
      ArrowDown: [0, 1],
      ArrowLeft: [-1, 0],
      ArrowRight: [1, 0],
    };
    const [dx, dy] = dir[e.key];

    let best: { id: string; score: number } | null = null;
    for (const nId of neighbors) {
      const nPos = positionById.current.get(nId);
      if (!nPos) continue;
      const vx = nPos.x - pos.x;
      const vy = nPos.y - pos.y;
      const len = Math.hypot(vx, vy) || 1;
      const score = (vx / len) * dx + (vy / len) * dy;
      if (score > 0 && (!best || score > best.score)) best = { id: nId, score };
    }

    if (best) {
      e.preventDefault();
      const nextEl = document.querySelector<HTMLElement>(`.react-flow__node[data-id="${CSS.escape(best.id)}"] [role="button"]`);
      nextEl?.focus();
      onNodeClick(best.id);
    }
  }

  return (
    <div className="h-full w-full" onKeyDown={handleKeyDown}>
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        onNodeClick={(_e, node) => onNodeClick(node.id)}
        fitView
        minZoom={0.2}
        maxZoom={2.5}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="oklch(1 0 0 / 0.04)" gap={28} />
        <Controls showInteractive={false} />
        <MiniMap
          pannable
          zoomable
          nodeColor={() => "oklch(0.55 0.05 280)"}
          maskColor="oklch(0.1 0.006 280 / 0.6)"
          style={{ background: "oklch(0.1 0.006 280 / 0.6)" }}
        />
      </ReactFlow>
    </div>
  );
}
