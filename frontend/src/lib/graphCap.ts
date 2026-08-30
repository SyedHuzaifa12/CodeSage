import type { GraphEdge } from "@/lib/types/workspace";

/**
 * Frontend connectivity cap for the interactive Graph page (Design System
 * §10/§17/B): the interactive `/call-graph` and `/dependency-graph`
 * endpoints are NOT guaranteed to be pre-capped by the backend the way
 * Sprint 6's Mermaid diagram builders are (~20-25 nodes there). This is a
 * documented, real backend gap — the frontend applies its own top-N by
 * connectivity (degree) cap so the graph stays readable and performant,
 * with an explicit escape hatch (increase the cap / filter by module).
 */
export const DEFAULT_GRAPH_NODE_CAP = 24;

export interface CappedGraph {
  nodes: string[];
  edges: GraphEdge[];
  totalNodes: number;
  degreeByNode: Map<string, number>;
}

export function capGraphByConnectivity(
  nodes: string[],
  edges: GraphEdge[],
  cap: number = DEFAULT_GRAPH_NODE_CAP,
): CappedGraph {
  const degreeByNode = new Map<string, number>();
  for (const node of nodes) degreeByNode.set(node, 0);
  for (const edge of edges) {
    degreeByNode.set(edge.source, (degreeByNode.get(edge.source) ?? 0) + 1);
    degreeByNode.set(edge.target, (degreeByNode.get(edge.target) ?? 0) + 1);
  }

  const ranked = [...nodes].sort((a, b) => (degreeByNode.get(b) ?? 0) - (degreeByNode.get(a) ?? 0));
  const kept = new Set(ranked.slice(0, cap));
  const cappedEdges = edges.filter((edge) => kept.has(edge.source) && kept.has(edge.target));

  return {
    nodes: ranked.slice(0, cap),
    edges: cappedEdges,
    totalNodes: nodes.length,
    degreeByNode,
  };
}
