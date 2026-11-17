import type { GraphEdge } from "@/lib/types/workspace";

/**
 * The graph model: pure functions over the backend's module graph. No React, no layout library, no randomness, so the
 * same repository always produces the same graph and everything here is unit-testable.
 *
 * Vocabulary
 * - module: one node from the backend (a dotted path such as `app.auth.routes`, or a symbol name in the call graph)
 * - group:  a folder/package that holds modules (`app.auth`). Groups nest, and can be collapsed into one box
 * - view:   what is drawn right now, given which groups are expanded. Collapsed groups stand in for their modules and
 *           the edges between them are merged into one weighted edge, which is what keeps a 500-module graph readable
 */

export type ModuleKind = "source" | "test" | "example" | "external";

export interface ModuleInfo {
  id: string;
  /** Last path segment: what is shown inside its group, where the folder is already on screen. */
  label: string;
  /** Id of the group that directly contains it, or null at the repository root. */
  group: string | null;
  kind: ModuleKind;
  inDegree: number;
  outDegree: number;
}

export interface GroupInfo {
  id: string;
  label: string;
  parent: string | null;
  groups: string[];
  modules: string[];
}

export interface GraphData {
  modules: ModuleInfo[];
  byId: Map<string, ModuleInfo>;
  groups: Map<string, GroupInfo>;
  /** Top-level groups, then nothing else: root-level modules have `group === null`. */
  rootGroups: string[];
  edges: GraphEdge[];
  dependsOn: Map<string, string[]>;
  usedBy: Map<string, string[]>;
}

const TEST_SEGMENTS = new Set(["tests", "test", "testing", "__tests__", "spec", "specs", "fuzzers", "benchmarks", "benchmark", "e2e"]);
const EXAMPLE_SEGMENTS = new Set(["examples", "example", "samples", "sample", "demo", "demos", "docs", "doc", "tutorials"]);

export function classifyModule(id: string, external: boolean): ModuleKind {
  if (external) return "external";
  const parts = id.split(".");
  const base = parts[parts.length - 1];
  if (parts.some((p) => TEST_SEGMENTS.has(p)) || base.startsWith("test_") || base.endsWith("_test") || base === "conftest") return "test";
  if (parts.some((p) => EXAMPLE_SEGMENTS.has(p))) return "example";
  return "source";
}

const byText = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

/**
 * Builds the model. `isInternal` says whether a node is a real file of the repository: nodes that are not (an imported
 * third-party package such as `pytest`) are kept but marked `external`, so they can be hidden instead of drawn as if they
 * were part of the project.
 */
export function buildGraphData(
  raw: { nodes: string[]; edges: GraphEdge[] },
  opts: { isInternal?: (id: string) => boolean } = {},
): GraphData {
  const seen = new Set<string>();
  const edges: GraphEdge[] = [];
  for (const e of raw.edges) {
    if (e.source === e.target) continue;
    const key = `${e.source}\u0000${e.target}`;
    if (seen.has(key)) continue;
    seen.add(key);
    edges.push({ source: e.source, target: e.target });
  }
  edges.sort((a, b) => byText(a.source, b.source) || byText(a.target, b.target));

  const ids = new Set(raw.nodes);
  for (const e of edges) {
    ids.add(e.source);
    ids.add(e.target);
  }
  const sortedIds = [...ids].sort(byText);

  const dependsOn = new Map<string, string[]>();
  const usedBy = new Map<string, string[]>();
  for (const id of sortedIds) {
    dependsOn.set(id, []);
    usedBy.set(id, []);
  }
  for (const e of edges) {
    dependsOn.get(e.source)!.push(e.target);
    usedBy.get(e.target)!.push(e.source);
  }

  // Group tree from the dotted paths: `a.b.c` lives in group `a.b`, which lives in `a`.
  const groups = new Map<string, GroupInfo>();
  const groupFor = (path: string): GroupInfo => {
    let g = groups.get(path);
    if (!g) {
      const cut = path.lastIndexOf(".");
      g = { id: path, label: path.slice(cut + 1), parent: cut === -1 ? null : path.slice(0, cut), groups: [], modules: [] };
      groups.set(path, g);
      if (g.parent) groupFor(g.parent).groups.push(path);
    }
    return g;
  };
  const modules: ModuleInfo[] = [];
  for (const id of sortedIds) {
    const cut = id.lastIndexOf(".");
    const group = cut === -1 ? null : id.slice(0, cut);
    if (group) groupFor(group).modules.push(id);
    modules.push({
      id,
      label: id.slice(cut + 1),
      group,
      kind: classifyModule(id, opts.isInternal ? !opts.isInternal(id) : false),
      inDegree: usedBy.get(id)!.length,
      outDegree: dependsOn.get(id)!.length,
    });
  }

  // A folder whose only content is one sub-folder (`com` > `company` > `app`) is just noise: fold it into that
  // sub-folder's label ("com.company"), which keeps deeply nested Java/JS trees from becoming a stack of empty boxes.
  let changed = true;
  while (changed) {
    changed = false;
    for (const g of [...groups.values()]) {
      if (g.modules.length === 0 && g.groups.length === 1 && groups.has(g.id)) {
        const child = groups.get(g.groups[0])!;
        child.label = `${g.label}.${child.label}`;
        child.parent = g.parent;
        if (g.parent) {
          const p = groups.get(g.parent)!;
          p.groups = p.groups.map((x) => (x === g.id ? child.id : x));
        }
        groups.delete(g.id);
        changed = true;
      }
    }
  }
  const rootGroups = [...groups.values()].filter((g) => g.parent === null).map((g) => g.id).sort(byText);
  for (const g of groups.values()) {
    g.groups.sort(byText);
    g.modules.sort(byText);
  }
  // Modules now point at their (possibly folded) group. A folded-away group id is replaced by its surviving child.
  for (const m of modules) {
    let gid = m.group;
    while (gid && !groups.has(gid)) {
      const cut = gid.lastIndexOf(".");
      gid = cut === -1 ? null : gid.slice(0, cut);
      // fall through to the nearest surviving ancestor; a folded group is never the direct owner of a module
    }
    m.group = gid;
  }
  // Recompute membership after folding so `group.modules` matches `module.group` exactly.
  for (const g of groups.values()) g.modules = [];
  for (const m of modules) if (m.group) groups.get(m.group)!.modules.push(m.id);

  const byId = new Map(modules.map((m) => [m.id, m]));
  return { modules, byId, groups, rootGroups, edges, dependsOn, usedBy };
}

// ---------------------------------------------------------------------------------------------------------------------
// Tangles (strongly connected components)
// ---------------------------------------------------------------------------------------------------------------------

export interface Tangle {
  index: number;
  members: string[];
}

/**
 * Sets of modules that all (transitively) depend on each other. The backend lists every individual cycle, which for a
 * real project is dozens of overlapping chains through the same few modules; the useful fact is the size of the one
 * knot they form, so cycles are folded into these. Tarjan's algorithm, iterative so a long import chain cannot overflow
 * the call stack.
 */
export function findTangles(data: Pick<GraphData, "modules" | "dependsOn">): Tangle[] {
  const index = new Map<string, number>();
  const low = new Map<string, number>();
  const onStack = new Set<string>();
  const stack: string[] = [];
  const out: string[][] = [];
  let counter = 0;

  for (const root of data.modules.map((m) => m.id)) {
    if (index.has(root)) continue;
    const work: { id: string; next: number }[] = [{ id: root, next: 0 }];
    index.set(root, counter);
    low.set(root, counter++);
    stack.push(root);
    onStack.add(root);
    while (work.length) {
      const frame = work[work.length - 1];
      const nbrs = data.dependsOn.get(frame.id) ?? [];
      if (frame.next < nbrs.length) {
        const w = nbrs[frame.next++];
        if (!index.has(w)) {
          index.set(w, counter);
          low.set(w, counter++);
          stack.push(w);
          onStack.add(w);
          work.push({ id: w, next: 0 });
        } else if (onStack.has(w)) {
          low.set(frame.id, Math.min(low.get(frame.id)!, index.get(w)!));
        }
      } else {
        if (low.get(frame.id) === index.get(frame.id)) {
          const comp: string[] = [];
          let w: string;
          do {
            w = stack.pop()!;
            onStack.delete(w);
            comp.push(w);
          } while (w !== frame.id);
          if (comp.length > 1) out.push(comp.sort(byText));
        }
        work.pop();
        if (work.length) {
          const parent = work[work.length - 1].id;
          low.set(parent, Math.min(low.get(parent)!, low.get(frame.id)!));
        }
      }
    }
  }
  return out
    .sort((a, b) => b.length - a.length || byText(a[0], b[0]))
    .map((members, i) => ({ index: i, members }));
}

export function tangleIndex(tangles: Tangle[]): Map<string, number> {
  const m = new Map<string, number>();
  for (const t of tangles) for (const id of t.members) m.set(id, t.index);
  return m;
}

// ---------------------------------------------------------------------------------------------------------------------
// The view: what is drawn for a given set of expanded groups
// ---------------------------------------------------------------------------------------------------------------------

export const DEFAULT_GROUP_LIMIT = 12;

export interface ViewOptions {
  /** Groups opened to show their contents; every other group is drawn as one box. */
  expanded: ReadonlySet<string>;
  /** Which kinds of module to include (tests, examples and external packages are off by default). */
  kinds: ReadonlySet<ModuleKind>;
  /** Per-group cap on modules drawn directly, raised by "show more". Defaults to DEFAULT_GROUP_LIMIT. */
  limits?: ReadonlyMap<string, number>;
  /** Modules that must be drawn even beyond the cap (the selected one, a search result). */
  pinned?: ReadonlySet<string>;
  /**
   * Leave out modules that import nothing and are imported by nothing (among the kinds shown). They have no place in a
   * dependency picture, and a pile of them is what makes a graph look like noise. They are counted, never silently lost.
   */
  hideUnconnected?: boolean;
  /**
   * Take the arrows into "hub" modules out of `edges` and report them separately. A hub is imported by a quarter of
   * everything drawn (helpers, base classes, shared types): it is important, but an arrow from every box to it carries
   * no information and is what turns a map into a hairball. The boxes are still marked, and the arrows reappear as soon
   * as one end is selected.
   */
  hideHubEdges?: boolean;
}

export interface GroupViewNode {
  kind: "group";
  id: string;
  groupId: string;
  label: string;
  parent: string | null;
  expanded: boolean;
  moduleCount: number;
}
export interface ModuleViewNode {
  kind: "module";
  id: string;
  moduleId: string;
  label: string;
  parent: string | null;
}
/** Stands in for the modules of a group that are not drawn individually ("+73 more"). */
export interface MoreViewNode {
  kind: "more";
  id: string;
  /** "" is the repository root. */
  groupId: string;
  hidden: number;
  parent: string | null;
}
export type ViewNode = GroupViewNode | ModuleViewNode | MoreViewNode;

export interface ViewEdge {
  id: string;
  source: string;
  target: string;
  /** How many module-to-module imports this one drawn edge stands for. */
  weight: number;
  /** True if any import it stands for lies inside a tangle. */
  tangled: boolean;
  /** Which tangle (see findTangles) the first such import belongs to. */
  tangle: number | null;
}

export interface GraphView {
  /** Parents come before their children, which React Flow requires. */
  nodes: ViewNode[];
  edges: ViewEdge[];
  includedModules: number;
  excludedByKind: number;
  /** Modules of a shown kind that were left out for having no connections. */
  unconnected: number;
  /** Modules imported by a large share of what is drawn (ids). Present whether or not their arrows are hidden. */
  hubs: string[];
  /** Arrows into hubs, left out of `edges` when `hideHubEdges` is set. */
  hubEdges: ViewEdge[];
}

export const moduleViewId = (id: string) => `m:${id}`;
export const groupViewId = (id: string) => `g:${id}`;
export const moreViewId = (groupId: string) => `more:${groupId}`;

function ancestorsOf(data: GraphData, m: ModuleInfo): string[] {
  const chain: string[] = [];
  let g = m.group;
  while (g) {
    chain.push(g);
    g = data.groups.get(g)!.parent;
  }
  return chain.reverse(); // outermost first
}

export function buildView(data: GraphData, opts: ViewOptions, tangles?: ReadonlyMap<string, number>): GraphView {
  const kindOk = (m: ModuleInfo) => opts.kinds.has(m.kind);
  const connected = (m: ModuleInfo) =>
    data.dependsOn.get(m.id)!.some((t) => kindOk(data.byId.get(t)!)) || data.usedBy.get(m.id)!.some((s) => kindOk(data.byId.get(s)!));
  const included = (m: ModuleInfo) => kindOk(m) && (!opts.hideUnconnected || connected(m) || opts.pinned?.has(m.id) === true);
  const moduleCount = new Map<string, number>();
  let includedModules = 0;
  for (const m of data.modules) {
    if (!included(m)) continue;
    includedModules++;
    for (const g of ancestorsOf(data, m)) moduleCount.set(g, (moduleCount.get(g) ?? 0) + 1);
  }

  const limitFor = (groupId: string) => opts.limits?.get(groupId) ?? DEFAULT_GROUP_LIMIT;
  /** Modules directly inside a group, split into those drawn and those folded into "+N more". */
  const split = (groupId: string, ids: string[]) => {
    const direct = ids
      .map((id) => data.byId.get(id)!)
      .filter(included)
      .sort((a, b) => b.inDegree - a.inDegree || byText(a.id, b.id));
    const cap = limitFor(groupId);
    const shown: ModuleInfo[] = [];
    const hidden: ModuleInfo[] = [];
    direct.forEach((m, i) => (i < cap || opts.pinned?.has(m.id) ? shown : hidden).push(m));
    return { shown, hidden };
  };

  const nodes: ViewNode[] = [];
  const repOfDirect = new Map<string, string>(); // module -> its own node (module or "more")
  const rootModules = data.modules.filter((m) => m.group === null).map((m) => m.id);

  const emitModules = (groupId: string, ids: string[], parent: string | null) => {
    const { shown, hidden } = split(groupId, ids);
    for (const m of shown) {
      nodes.push({ kind: "module", id: moduleViewId(m.id), moduleId: m.id, label: m.label, parent });
      repOfDirect.set(m.id, moduleViewId(m.id));
    }
    if (hidden.length) {
      nodes.push({ kind: "more", id: moreViewId(groupId), groupId, hidden: hidden.length, parent });
      for (const m of hidden) repOfDirect.set(m.id, moreViewId(groupId));
    }
  };
  const emitGroup = (groupId: string, parent: string | null) => {
    const g = data.groups.get(groupId)!;
    const open = opts.expanded.has(groupId);
    const id = groupViewId(groupId);
    nodes.push({ kind: "group", id, groupId, label: g.label, parent, expanded: open, moduleCount: moduleCount.get(groupId) ?? 0 });
    if (!open) return;
    for (const sub of g.groups) if (moduleCount.get(sub)) emitGroup(sub, id);
    emitModules(groupId, g.modules, id);
  };
  for (const gid of data.rootGroups) if (moduleCount.get(gid)) emitGroup(gid, null);
  emitModules("", rootModules, null);

  const repOf = (m: ModuleInfo): string | undefined => {
    for (const g of ancestorsOf(data, m)) if (!opts.expanded.has(g)) return groupViewId(g);
    return repOfDirect.get(m.id);
  };

  // Hubs: imported by at least a quarter of the drawn modules (and never fewer than 8).
  const importers = new Map<string, number>();
  for (const e of data.edges) {
    const s = data.byId.get(e.source)!;
    const t = data.byId.get(e.target)!;
    if (included(s) && included(t)) importers.set(e.target, (importers.get(e.target) ?? 0) + 1);
  }
  const hubMin = Math.max(8, Math.ceil(includedModules * 0.25));
  const hubSet = new Set([...importers].filter(([, n]) => n >= hubMin).map(([id]) => id));

  const merged = new Map<string, ViewEdge>();
  for (const e of data.edges) {
    const s = data.byId.get(e.source)!;
    const t = data.byId.get(e.target)!;
    if (!included(s) || !included(t)) continue;
    const rs = repOf(s);
    const rt = repOf(t);
    if (!rs || !rt || rs === rt) continue;
    const id = `${rs}→${rt}`;
    const tangle = tangles !== undefined && tangles.has(e.source) && tangles.get(e.source) === tangles.get(e.target) ? tangles.get(e.source)! : null;
    const cur = merged.get(id);
    if (cur) {
      cur.weight++;
      if (cur.tangle === null && tangle !== null) {
        cur.tangle = tangle;
        cur.tangled = true;
      }
    } else merged.set(id, { id, source: rs, target: rt, weight: 1, tangled: tangle !== null, tangle });
  }
  const all = [...merged.values()].sort((a, b) => byText(a.id, b.id));
  const intoHub = (e: ViewEdge) => e.target.startsWith("m:") && hubSet.has(e.target.slice(2));
  const edges = opts.hideHubEdges ? all.filter((e) => !intoHub(e)) : all;
  const hubEdges = opts.hideHubEdges ? all.filter(intoHub) : [];
  const ofShownKinds = data.modules.filter(kindOk).length;
  const hubs = [...hubSet].filter((id) => repOfDirect.get(id) === moduleViewId(id)).sort(byText);
  return { nodes, edges, includedModules, excludedByKind: data.modules.length - ofShownKinds, unconnected: ofShownKinds - includedModules, hubs, hubEdges };
}

/**
 * The groups to open first, so the opening picture is neither one lonely box nor a wall of modules: open the largest
 * collapsed group, repeatedly, until about `target` things are on screen, never past `max`.
 */
export function suggestExpansion(
  data: GraphData,
  kinds: ReadonlySet<ModuleKind>,
  opts: { target?: number; max?: number } = {},
): Set<string> {
  const target = opts.target ?? 14;
  const max = opts.max ?? 60;
  const expanded = new Set<string>();
  let view = buildView(data, { expanded, kinds });
  while (view.nodes.length < target) {
    const candidates = view.nodes
      .filter((n): n is GroupViewNode => n.kind === "group" && !n.expanded)
      .sort((a, b) => b.moduleCount - a.moduleCount || byText(a.groupId, b.groupId));
    let opened = false;
    for (const c of candidates) {
      const next = buildView(data, { expanded: new Set([...expanded, c.groupId]), kinds });
      if (next.nodes.length > max) continue;
      expanded.add(c.groupId);
      view = next;
      opened = true;
      break;
    }
    if (!opened) break;
  }
  return expanded;
}

// ---------------------------------------------------------------------------------------------------------------------
// Queries the UI needs
// ---------------------------------------------------------------------------------------------------------------------

/** The modules with the most dependents: the "key modules" a newcomer should read first. */
export function topByDependents(data: GraphData, kinds: ReadonlySet<ModuleKind>, n: number): ModuleInfo[] {
  // Count only dependents that are themselves shown: a module used by ten tests is not a key module of the product.
  const used = (m: ModuleInfo) => data.usedBy.get(m.id)!.filter((s) => kinds.has(data.byId.get(s)!.kind)).length;
  return data.modules
    .filter((m) => kinds.has(m.kind))
    .map((m) => ({ m, n: used(m) }))
    .filter((x) => x.n > 0)
    .sort((a, b) => b.n - a.n || byText(a.m.id, b.m.id))
    .slice(0, n)
    .map((x) => x.m);
}

export function searchModules(data: GraphData, query: string, kinds: ReadonlySet<ModuleKind>, limit = 8): ModuleInfo[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const scored: { m: ModuleInfo; score: number }[] = [];
  for (const m of data.modules) {
    if (!kinds.has(m.kind)) continue;
    const id = m.id.toLowerCase();
    const label = m.label.toLowerCase();
    const score = label === q ? 0 : label.startsWith(q) ? 1 : id.includes(q) ? 2 : -1;
    if (score >= 0) scored.push({ m, score });
  }
  return scored
    .sort((a, b) => a.score - b.score || b.m.inDegree - a.m.inDegree || byText(a.m.id, b.m.id))
    .slice(0, limit)
    .map((s) => s.m);
}

/** Every group that has to be open for `moduleId` to be drawn. */
export function groupsToReveal(data: GraphData, moduleId: string): string[] {
  const m = data.byId.get(moduleId);
  return m ? ancestorsOf(data, m) : [];
}

/** The group a module is in, as shown to people: "aiohttp" or "tests.autobahn"; the repository root is "(root)". */
export function groupLabelOf(data: GraphData, m: ModuleInfo): string {
  if (!m.group) return "(root)";
  const parts: string[] = [];
  let g: string | null = m.group;
  while (g) {
    const info: GroupInfo = data.groups.get(g)!;
    parts.unshift(info.label);
    g = info.parent;
  }
  return parts.join(".");
}
