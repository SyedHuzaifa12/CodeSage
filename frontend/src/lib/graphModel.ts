import type { GraphEdge, TreeNode } from "@/lib/types/workspace";

/**
 * Graph/file identity helpers shared by Overview, Explorer and Graph.
 *
 * The backend identifies dependency-graph nodes by dotted *module paths*
 * (`app/auth/routes.py` -> `app.auth.routes`, see
 * backend/app/ingestion/parsers/base.py::module_path_from_relative_path)
 * and call-graph nodes by symbol *qualified names*. Symbols and the file
 * tree use repository-relative *file paths*. Every page that crosses
 * between the two must go through these helpers — the Sprint 7 Graph panel
 * compared a module path to a file path directly and always came up empty.
 */

/** `app/auth/routes.py` -> `app.auth.routes` (mirrors the backend exactly). */
export function fileToModule(path: string): string {
  const last = path.split("/").pop() ?? path;
  const withoutExt = last.includes(".") ? path.slice(0, path.lastIndexOf(".")) : path;
  return withoutExt.replace(/\//g, ".");
}

/** The backend emits `type: "folder"`; older client code expected `"directory"`. Accept both. */
export function isFolderNode(node: Pick<TreeNode, "type" | "children">): boolean {
  return node.type === "folder" || node.type === "directory" || (Array.isArray(node.children) && node.type !== "file");
}

export function flattenTreeFiles(nodes: TreeNode[] | undefined): TreeNode[] {
  const out: TreeNode[] = [];
  const walk = (list: TreeNode[]) => {
    for (const n of list) {
      if (isFolderNode(n)) walk(n.children ?? []);
      else out.push(n);
    }
  };
  walk(nodes ?? []);
  return out;
}

/** module path -> file path, built from the real file list. */
export function buildModuleIndex(filePaths: Iterable<string>): Map<string, string> {
  const index = new Map<string, string>();
  for (const p of filePaths) index.set(fileToModule(p), p);
  return index;
}

/** Directed edge keys (`a→b`) for every consecutive pair in each cycle, including the wrap-around. */
export function cycleEdgeKeys(cycles: string[][]): Set<string> {
  const keys = new Set<string>();
  for (const cycle of cycles) {
    for (let i = 0; i < cycle.length; i++) {
      keys.add(`${cycle[i]}→${cycle[(i + 1) % cycle.length]}`);
    }
  }
  return keys;
}

export const edgeKey = (e: GraphEdge) => `${e.source}→${e.target}`;

export interface GraphModel {
  nodes: string[];
  edges: GraphEdge[];
  /** Every de-duplicated edge in the (optionally prefix-filtered) graph — for in/out lists beyond the cap. */
  allEdges: GraphEdge[];
  degree: Map<string, number>;
  inDegree: Map<string, number>;
  outDegree: Map<string, number>;
  totalNodes: number;
}

/**
 * Frontend connectivity cap (Design System §10): the interactive graph
 * endpoints are not pre-capped server-side, so the client keeps the top-N
 * nodes by degree. Optional `prefix` restricts the graph to one module
 * area before capping — a client-side filter over data already loaded.
 */
export function buildGraphModel(
  nodes: string[],
  edges: GraphEdge[],
  opts: { cap?: number; prefix?: string | null } = {},
): GraphModel {
  const cap = opts.cap ?? 24;
  const prefix = opts.prefix && opts.prefix !== "all" ? opts.prefix : null;
  const seen = new Set<string>();
  const unique: GraphEdge[] = [];
  for (const e of edges) {
    if (e.source === e.target) continue;
    const k = edgeKey(e);
    if (seen.has(k)) continue;
    seen.add(k);
    unique.push(e);
  }
  const inScope = (n: string) => !prefix || n === prefix || n.startsWith(`${prefix}.`);
  const scopedNodes = nodes.filter(inScope);
  const scopedSet = new Set(scopedNodes);
  const scopedEdges = unique.filter((e) => scopedSet.has(e.source) && scopedSet.has(e.target));

  const degree = new Map<string, number>();
  for (const n of scopedNodes) degree.set(n, 0);
  for (const e of scopedEdges) {
    degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
    degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
  }
  const ranked = [...scopedNodes]
    .filter((n) => (degree.get(n) ?? 0) > 0 || scopedNodes.length <= cap)
    .sort((a, b) => (degree.get(b) ?? 0) - (degree.get(a) ?? 0) || a.localeCompare(b));
  const kept = ranked.slice(0, cap);
  const keptSet = new Set(kept);
  const keptEdges = scopedEdges.filter((e) => keptSet.has(e.source) && keptSet.has(e.target));
  const inDegree = new Map<string, number>();
  const outDegree = new Map<string, number>();
  for (const n of kept) {
    inDegree.set(n, 0);
    outDegree.set(n, 0);
  }
  for (const e of keptEdges) {
    outDegree.set(e.source, (outDegree.get(e.source) ?? 0) + 1);
    inDegree.set(e.target, (inDegree.get(e.target) ?? 0) + 1);
  }
  return { nodes: kept, edges: keptEdges, allEdges: scopedEdges, degree, inDegree, outDegree, totalNodes: nodes.length };
}

export function neighborsOf(edges: GraphEdge[], node: string): Set<string> {
  const out = new Set<string>();
  for (const e of edges) {
    if (e.source === node) out.add(e.target);
    if (e.target === node) out.add(e.source);
  }
  return out;
}

/** Leading dotted segments shared by every node — stripped from labels so they stay readable. */
export function sharedPrefixDepth(nodes: string[]): number {
  if (nodes.length < 2) return 0;
  const parts = nodes.map((n) => n.split("."));
  let depth = 0;
  while (parts.every((p) => p.length > depth + 1 && p[depth] === parts[0][depth])) depth++;
  return depth;
}

export function nodeLabel(node: string, mode: "dependency" | "call", prefixDepth = 0): string {
  const parts = node.split(".");
  if (mode === "call") return parts.slice(-2).join(".");
  return parts.slice(Math.min(prefixDepth, parts.length - 1)).join(".");
}

/** The most populated two-segment module areas — used as client-side focus filters. */
export function moduleAreas(nodes: string[], limit = 7): string[] {
  const counts = new Map<string, number>();
  for (const n of nodes) {
    const parts = n.split(".");
    if (parts.length < 2) continue;
    const area = parts.slice(0, Math.min(2, parts.length - 1)).join(".");
    counts.set(area, (counts.get(area) ?? 0) + 1);
  }
  return [...counts.entries()]
    .filter(([, c]) => c >= 2)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, limit)
    .map(([k]) => k);
}

/** Dependency risk classification — mirrors backend/app/reports/generators/dependency_risk.py (threshold 5). */
export const HIGH_RISK_INCOMING_THRESHOLD = 5;
export function classifyRisk(modulePath: string, incoming: number, cycles: string[][]): "high" | "medium" | "low" {
  const inCycle = cycles.some((c) => c.includes(modulePath));
  if (inCycle && incoming >= HIGH_RISK_INCOMING_THRESHOLD) return "high";
  if (inCycle || incoming >= HIGH_RISK_INCOMING_THRESHOLD) return "medium";
  return "low";
}
