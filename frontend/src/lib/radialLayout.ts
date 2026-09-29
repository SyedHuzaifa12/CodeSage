import type { GraphEdge } from "@/lib/types/workspace";

export interface RadialNode {
  id: string;
  x: number;
  y: number;
  degree: number;
  ring: 0 | 1 | 2;
}

export interface RadialLayout {
  nodes: RadialNode[];
  edges: GraphEdge[];
  width: number;
  height: number;
}

/**
 * A small, deterministic radial layout for Overview's illustrative topology
 * diagram (Design System §17: "the topology diagram is the dominant visual
 * ... annotated directly"). Not a general-purpose graph layout algorithm —
 * intentionally simple (highest-degree node at center, next-highest in a
 * ring, remainder further out) since this is a static preview, not the
 * interactive Graph page (which uses @xyflow/react's real layout/pan/zoom).
 */
export function computeRadialLayout(nodes: string[], edges: GraphEdge[], maxNodes = 9): RadialLayout {
  const width = 760;
  const height = 560;
  const cx = width / 2;
  const cy = height / 2;

  const degree = new Map<string, number>();
  for (const n of nodes) degree.set(n, 0);
  for (const e of edges) {
    degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
    degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
  }

  const ranked = [...nodes].sort((a, b) => (degree.get(b) ?? 0) - (degree.get(a) ?? 0)).slice(0, maxNodes);
  if (ranked.length === 0) return { nodes: [], edges: [], width, height };

  const [root, ...rest] = ranked;
  const ringNodes = rest.slice(0, 5);
  const outerNodes = rest.slice(5);

  const laidOut: RadialNode[] = [{ id: root, x: cx, y: cy, degree: degree.get(root) ?? 0, ring: 0 }];

  ringNodes.forEach((id, i) => {
    const angle = (i / Math.max(ringNodes.length, 1)) * Math.PI * 2 - Math.PI / 2;
    laidOut.push({
      id,
      x: cx + Math.cos(angle) * 170,
      y: cy + Math.sin(angle) * 150,
      degree: degree.get(id) ?? 0,
      ring: 1,
    });
  });

  outerNodes.forEach((id, i) => {
    const angle = (i / Math.max(outerNodes.length, 1)) * Math.PI * 2 - Math.PI / 2 + Math.PI / (ringNodes.length || 1);
    laidOut.push({
      id,
      x: cx + Math.cos(angle) * 280,
      y: cy + Math.sin(angle) * 240,
      degree: degree.get(id) ?? 0,
      ring: 2,
    });
  });

  const kept = new Set(laidOut.map((n) => n.id));
  const keptEdges = edges.filter((e) => kept.has(e.source) && kept.has(e.target));

  return { nodes: laidOut, edges: keptEdges, width, height };
}
