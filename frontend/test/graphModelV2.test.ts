import { describe, expect, it } from "vitest";
import {
  buildGraphData,
  buildView,
  classifyModule,
  findTangles,
  groupLabelOf,
  groupsToReveal,
  searchModules,
  suggestExpansion,
  tangleIndex,
  topByDependents,
  type ModuleKind,
} from "@/lib/graph/model";

const e = (source: string, target: string) => ({ source, target });
const SOURCE: ReadonlySet<ModuleKind> = new Set(["source"]);
const ALL: ReadonlySet<ModuleKind> = new Set(["source", "test", "example", "external"]);

const sample = () =>
  buildGraphData({
    nodes: ["app.auth.routes", "app.auth.service", "app.db.session", "app.main", "tests.test_auth", "pytest"],
    edges: [
      e("app.main", "app.auth.routes"),
      e("app.auth.routes", "app.auth.service"),
      e("app.auth.service", "app.db.session"),
      e("app.auth.routes", "app.db.session"),
      e("tests.test_auth", "app.auth.service"),
      e("tests.test_auth", "pytest"),
    ],
  }, { isInternal: (id) => id !== "pytest" });

describe("classifyModule", () => {
  it("separates tests, examples, external packages and source", () => {
    expect(classifyModule("app.tests.test_x", false)).toBe("test");
    expect(classifyModule("app.test_x", false)).toBe("test");
    expect(classifyModule("docs.examples.demo", false)).toBe("example");
    expect(classifyModule("anything", true)).toBe("external");
    expect(classifyModule("app.auth", false)).toBe("source");
  });
});

describe("buildGraphData", () => {
  it("builds the group tree from dotted paths and counts degrees", () => {
    const d = sample();
    expect(d.rootGroups).toEqual(["app", "tests"]);
    expect(d.groups.get("app")!.groups).toEqual(["app.auth", "app.db"]);
    expect(d.byId.get("app.db.session")!.inDegree).toBe(2);
    expect(d.byId.get("app.auth.routes")!.label).toBe("routes");
    expect(d.byId.get("pytest")!.kind).toBe("external");
    expect(d.byId.get("tests.test_auth")!.kind).toBe("test");
  });

  it("drops self loops and duplicate edges", () => {
    const d = buildGraphData({ nodes: ["a.x", "a.y"], edges: [e("a.x", "a.x"), e("a.x", "a.y"), e("a.x", "a.y")] });
    expect(d.edges).toHaveLength(1);
  });

  it("is identical for shuffled input (deterministic)", () => {
    const a = sample();
    const b = buildGraphData(
      {
        nodes: ["pytest", "tests.test_auth", "app.main", "app.db.session", "app.auth.service", "app.auth.routes"],
        edges: [...sample().edges].reverse(),
      },
      { isInternal: (id) => id !== "pytest" },
    );
    expect(b.modules.map((m) => m.id)).toEqual(a.modules.map((m) => m.id));
    expect(b.edges).toEqual(a.edges);
  });

  it("folds a chain of single-child folders into one labelled group", () => {
    const d = buildGraphData({ nodes: ["com.acme.shop.Cart", "com.acme.shop.Order"], edges: [] });
    expect(d.rootGroups).toEqual(["com.acme.shop"]);
    expect(d.groups.get("com.acme.shop")!.label).toBe("com.acme.shop");
    expect(d.groups.get("com.acme.shop")!.modules).toEqual(["com.acme.shop.Cart", "com.acme.shop.Order"]);
  });

  it("keeps modules at the repository root without a group", () => {
    const d = buildGraphData({ nodes: ["setup", "app.x"], edges: [] });
    expect(d.byId.get("setup")!.group).toBeNull();
    expect(groupLabelOf(d, d.byId.get("setup")!)).toBe("(root)");
  });
});

describe("findTangles", () => {
  it("folds overlapping cycles into one knot and ignores acyclic code", () => {
    const d = buildGraphData({
      nodes: [],
      edges: [e("a.x", "a.y"), e("a.y", "a.z"), e("a.z", "a.x"), e("a.y", "a.x"), e("a.z", "b.leaf")],
    });
    const t = findTangles(d);
    expect(t).toHaveLength(1);
    expect(t[0].members).toEqual(["a.x", "a.y", "a.z"]);
    expect(tangleIndex(t).has("b.leaf")).toBe(false);
  });

  it("survives a very long import chain without overflowing the stack", () => {
    const edges = Array.from({ length: 20000 }, (_, i) => e(`p.m${i}`, `p.m${i + 1}`));
    edges.push(e("p.m20000", "p.m0"));
    const t = findTangles(buildGraphData({ nodes: [], edges }));
    expect(t).toHaveLength(1);
    expect(t[0].members).toHaveLength(20001);
  });
});

describe("buildView", () => {
  it("collapses groups into boxes and merges their edges with a count", () => {
    const d = sample();
    const v = buildView(d, { expanded: new Set(), kinds: SOURCE });
    expect(v.nodes.map((n) => n.id)).toEqual(["g:app", "m:setup"].filter((id) => id === "g:app"));
    expect(v.edges).toEqual([]); // everything is inside `app`
    expect(v.excludedByKind).toBe(2);
  });

  it("shows aggregated edges between collapsed sub-groups", () => {
    const d = sample();
    const v = buildView(d, { expanded: new Set(["app"]), kinds: SOURCE });
    const ids = v.nodes.map((n) => n.id);
    expect(ids).toEqual(["g:app", "g:app.auth", "g:app.db", "m:app.main"]);
    const auth2db = v.edges.find((x) => x.id === "g:app.auth→g:app.db")!;
    expect(auth2db.weight).toBe(2);
    expect(v.edges.find((x) => x.id === "m:app.main→g:app.auth")!.weight).toBe(1);
  });

  it("lists parents before children (React Flow requires it)", () => {
    const d = sample();
    const v = buildView(d, { expanded: new Set(["app", "app.auth"]), kinds: SOURCE });
    const order = new Map(v.nodes.map((n, i) => [n.id, i]));
    for (const n of v.nodes) if (n.parent) expect(order.get(n.parent)!).toBeLessThan(order.get(n.id)!);
  });

  it("hides tests and external packages unless asked, and says how many it hid", () => {
    const d = sample();
    expect(buildView(d, { expanded: new Set(), kinds: SOURCE }).excludedByKind).toBe(2);
    const all = buildView(d, { expanded: new Set(), kinds: ALL });
    expect(all.excludedByKind).toBe(0);
    expect(all.nodes.some((n) => n.id === "m:pytest")).toBe(true);
  });

  it("caps a crowded folder and stands in '+N more' without losing edges", () => {
    const nodes = Array.from({ length: 40 }, (_, i) => `big.m${String(i).padStart(2, "0")}`);
    const edges = nodes.map((n) => e("hub.main", n));
    const d = buildGraphData({ nodes: [...nodes, "hub.main"], edges });
    const v = buildView(d, { expanded: new Set(["big", "hub"]), kinds: SOURCE, limits: new Map([["big", 10]]) });
    const more = v.nodes.find((n) => n.kind === "more")!;
    expect(more.kind === "more" && more.hidden).toBe(30);
    const toMore = v.edges.find((x) => x.target === "more:big")!;
    expect(toMore.weight).toBe(30);
  });

  it("keeps a pinned module visible even past the cap", () => {
    const nodes = Array.from({ length: 20 }, (_, i) => `big.m${String(i).padStart(2, "0")}`);
    const d = buildGraphData({ nodes, edges: [] });
    const v = buildView(d, { expanded: new Set(["big"]), kinds: SOURCE, limits: new Map([["big", 3]]), pinned: new Set(["big.m19"]) });
    expect(v.nodes.some((n) => n.id === "m:big.m19")).toBe(true);
  });

  it("marks edges inside a tangle", () => {
    const d = buildGraphData({ nodes: [], edges: [e("a.x", "a.y"), e("a.y", "a.x"), e("a.x", "a.z")] });
    const v = buildView(d, { expanded: new Set(["a"]), kinds: SOURCE }, tangleIndex(findTangles(d)));
    expect(v.edges.find((x) => x.id === "m:a.x→m:a.y")!.tangled).toBe(true);
    expect(v.edges.find((x) => x.id === "m:a.x→m:a.z")!.tangled).toBe(false);
  });

  it("is deterministic for shuffled input", () => {
    const a = buildView(sample(), { expanded: new Set(["app"]), kinds: SOURCE });
    const shuffled = buildGraphData({ nodes: [], edges: [...sample().edges].reverse() }, { isInternal: (id) => id !== "pytest" });
    const b = buildView(shuffled, { expanded: new Set(["app"]), kinds: SOURCE });
    expect(b.nodes).toEqual(a.nodes);
    expect(b.edges).toEqual(a.edges);
  });
});

describe("suggestExpansion", () => {
  it("opens the biggest groups until the picture is useful, never past the max", () => {
    const nodes: string[] = [];
    for (const g of ["a", "b", "c"]) for (let i = 0; i < 6; i++) nodes.push(`${g}.m${i}`);
    const d = buildGraphData({ nodes, edges: [] });
    const open = suggestExpansion(d, SOURCE, { target: 8, max: 30 });
    expect(open.size).toBeGreaterThan(0);
    expect(buildView(d, { expanded: open, kinds: SOURCE }).nodes.length).toBeLessThanOrEqual(30);
  });

  it("does not open anything that would blow the budget", () => {
    const nodes = Array.from({ length: 200 }, (_, i) => `huge.m${i}`);
    const d = buildGraphData({ nodes, edges: [] });
    const open = suggestExpansion(d, SOURCE, { target: 5, max: 20 });
    expect(buildView(d, { expanded: open, kinds: SOURCE }).nodes.length).toBeLessThanOrEqual(50);
  });
});

describe("queries", () => {
  it("ranks key modules by how many others depend on them", () => {
    expect(topByDependents(sample(), SOURCE, 2).map((m) => m.id)).toEqual(["app.db.session", "app.auth.routes"]);
  });

  it("searches by name first, then by path, and respects the kind filter", () => {
    const d = sample();
    expect(searchModules(d, "session", SOURCE)[0].id).toBe("app.db.session");
    expect(searchModules(d, "pytest", SOURCE)).toEqual([]);
    expect(searchModules(d, "pytest", ALL)[0].id).toBe("pytest");
    expect(searchModules(d, "  ", SOURCE)).toEqual([]);
  });

  it("names the groups that must be open to reveal a module", () => {
    expect(groupsToReveal(sample(), "app.auth.routes")).toEqual(["app", "app.auth"]);
  });
});

describe("buildView unconnected modules", () => {
  it("leaves out modules with no connections, counts them, and keeps a pinned one", () => {
    const d = buildGraphData({ nodes: ["a.x", "a.y", "a.lonely"], edges: [e("a.x", "a.y")] });
    const base = { expanded: new Set(["a"]), kinds: SOURCE, hideUnconnected: true };
    const v = buildView(d, base);
    expect(v.nodes.some((n) => n.id === "m:a.lonely")).toBe(false);
    expect(v.unconnected).toBe(1);
    expect(buildView(d, { ...base, pinned: new Set(["a.lonely"]) }).nodes.some((n) => n.id === "m:a.lonely")).toBe(true);
    expect(buildView(d, { ...base, hideUnconnected: false }).nodes.some((n) => n.id === "m:a.lonely")).toBe(true);
  });
});

describe("hub modules", () => {
  const hubGraph = () => {
    const users = Array.from({ length: 10 }, (_, i) => `app.u${i}`);
    return buildGraphData({ nodes: [], edges: [...users.map((u) => e(u, "app.helpers")), e("app.u0", "app.u1"), e("app.u1", "app.u2")] });
  };
  const base = { expanded: new Set(["app"]), kinds: SOURCE };

  it("reports modules imported by a large share of the picture, and can take their arrows out of the way", () => {
    const d = hubGraph();
    const shown = buildView(d, base);
    expect(shown.hubs).toEqual(["app.helpers"]);
    expect(shown.hubEdges).toEqual([]);
    expect(shown.edges).toHaveLength(12);

    const folded = buildView(d, { ...base, hideHubEdges: true });
    expect(folded.edges).toHaveLength(2);
    expect(folded.hubEdges).toHaveLength(10);
    expect(folded.hubs).toEqual(["app.helpers"]);
  });

  it("does not call anything a hub in a small graph", () => {
    const d = buildGraphData({ nodes: [], edges: [e("a.x", "a.core"), e("a.y", "a.core"), e("a.z", "a.core")] });
    expect(buildView(d, { expanded: new Set(["a"]), kinds: SOURCE }).hubs).toEqual([]);
  });

  it("carries the tangle index on an edge so only the selected knot is drawn as a loop", () => {
    const d = buildGraphData({ nodes: [], edges: [e("a.x", "a.y"), e("a.y", "a.x")] });
    const v = buildView(d, { expanded: new Set(["a"]), kinds: SOURCE }, tangleIndex(findTangles(d)));
    expect(v.edges.every((x) => x.tangle === 0)).toBe(true);
  });
});

describe("module index for classification", () => {
  it("does not let a config file make a library look like part of the project", async () => {
    const { buildModuleIndex, isParsedSourceFile } = await import("@/lib/graphModel");
    const index = buildModuleIndex(["pytest.ini", "setup.cfg", "app/main.py", "web/ui.tsx"].filter(isParsedSourceFile));
    expect([...index.keys()].sort()).toEqual(["app.main", "web.ui"]);
  });
});
