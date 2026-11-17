import type { ElkNode, LayoutOptions } from "elkjs/lib/elk-api";
import type { GraphView, ViewNode } from "./model";

/**
 * Turns a GraphView into positions with the ELK "layered" algorithm: dependencies flow top to bottom, each box sits in
 * the row below the things that depend on it, and folders are drawn as boxes around their modules.
 *
 * This file does not import elkjs itself: the engine is passed in, so the heavy bundle can live in a web worker and
 * tests can run it in Node. Determinism: ids are sorted before the graph is built and the random seed is fixed, so the
 * same repository is always drawn the same way (a map that rearranges itself on every visit cannot be learned).
 */

export interface Placed {
  /** Relative to the parent box (React Flow's convention for nodes with a parent). */
  x: number;
  y: number;
  width: number;
  height: number;
}
export interface LayoutResult {
  positions: Record<string, Placed>;
  width: number;
  height: number;
}
export interface LayoutEngine {
  layout(graph: ElkNode): Promise<ElkNode>;
}

export const MODULE_HEIGHT = 34;
export const COLLAPSED_GROUP = { width: 196, height: 64 };
export const GROUP_HEADER = 40;

/** Width follows the label so a name is never cut off, within sane bounds. */
export function sizeOf(node: ViewNode): { width: number; height: number } {
  switch (node.kind) {
    case "module":
      // The label in 12px monospace, plus room for the usage count and up to two marker icons: a clipped name defeats the map.
      return { width: clamp(node.label.length * 7.3 + 84, 112, 290), height: MODULE_HEIGHT };
    case "more":
      return { width: 132, height: MODULE_HEIGHT };
    case "group":
      return COLLAPSED_GROUP;
  }
}
const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, Math.round(n)));

export const ROOT_OPTIONS: LayoutOptions = {
  "elk.algorithm": "layered",
  // Top to bottom reads as layers: what starts the program at the top, the code it relies on underneath. It is also much
  // more compact than left to right for a typical package (a few wide rows rather than a long chain of columns).
  "elk.direction": "DOWN",
  // Each folder is laid out on its own (cheap), with cross-folder imports lifted to the level where the two sides are
  // siblings (see toElkGraph). Laying the whole nested graph out in one pass is far slower on a real project: tens of
  // seconds for a couple of hundred modules, which is not acceptable in a browser.
  "elk.hierarchyHandling": "SEPARATE_CHILDREN",
  "elk.randomSeed": "1",
  "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
  "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
  "elk.layered.spacing.nodeNodeBetweenLayers": "48",
  "elk.spacing.nodeNode": "20",
  "elk.spacing.componentComponent": "40",
  "elk.separateConnectedComponents": "true",
  "elk.padding": "[top=12,left=12,bottom=12,right=12]",
};
/** Layout options are not inherited by a nested box, so every folder repeats the root's, with room for its header. */
const groupOptions = (root: LayoutOptions): LayoutOptions => ({ ...root, "elk.padding": `[top=${GROUP_HEADER},left=18,bottom=18,right=18]` });

export function toElkGraph(view: GraphView, rootOptions: LayoutOptions = ROOT_OPTIONS): ElkNode {
  const parentOf = new Map<string, string | null>(view.nodes.map((n) => [n.id, n.parent]));
  const children = new Map<string | null, ViewNode[]>();
  for (const n of view.nodes) {
    const list = children.get(n.parent) ?? [];
    list.push(n);
    children.set(n.parent, list);
  }
  const chain = (id: string): string[] => {
    const out: string[] = [];
    for (let c: string | null | undefined = id; c; c = parentOf.get(c)) out.push(c);
    return out.reverse(); // outermost first
  };

  // An import between two boxes in different folders is represented, at the level where those folders are siblings, as
  // one edge between the two siblings. That is what makes `app.auth` sit left of `app.db` when auth imports db.
  const lifted = new Map<string | null, Map<string, { s: string; t: string }>>();
  for (const e of view.edges) {
    const a = chain(e.source);
    const b = chain(e.target);
    let i = 0;
    while (i < a.length && i < b.length && a[i] === b[i]) i++;
    if (i >= a.length || i >= b.length) continue;
    const scope = i === 0 ? null : a[i - 1];
    const key = `${a[i]}→${b[i]}`;
    const bucket = lifted.get(scope) ?? new Map();
    bucket.set(key, { s: a[i], t: b[i] });
    lifted.set(scope, bucket);
  }
  const edgesIn = (scope: string | null) =>
    [...(lifted.get(scope)?.entries() ?? [])]
      .sort(([x], [y]) => (x < y ? -1 : x > y ? 1 : 0))
      .map(([key, v]) => ({ id: `${scope ?? "root"}|${key}`, sources: [v.s], targets: [v.t] }));

  const build = (n: ViewNode): ElkNode => {
    if (n.kind === "group" && n.expanded) {
      return { id: n.id, layoutOptions: groupOptions(rootOptions), children: (children.get(n.id) ?? []).map(build), edges: edgesIn(n.id) };
    }
    return { id: n.id, ...sizeOf(n) };
  };
  return {
    id: "root",
    layoutOptions: rootOptions,
    children: (children.get(null) ?? []).map(build),
    edges: edgesIn(null),
  };
}

export async function computeLayout(engine: LayoutEngine, view: GraphView): Promise<LayoutResult> {
  if (view.nodes.length === 0) return { positions: {}, width: 0, height: 0 };
  const out = await engine.layout(toElkGraph(view));
  const positions: Record<string, Placed> = {};
  const walk = (n: ElkNode) => {
    for (const c of n.children ?? []) {
      positions[c.id] = { x: c.x ?? 0, y: c.y ?? 0, width: c.width ?? 0, height: c.height ?? 0 };
      walk(c);
    }
  };
  walk(out);
  return { positions, width: out.width ?? 0, height: out.height ?? 0 };
}
