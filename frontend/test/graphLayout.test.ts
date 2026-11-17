// @vitest-environment node
import ELK from "elkjs/lib/elk.bundled.js";
import { describe, expect, it } from "vitest";
import { computeLayout } from "@/lib/graph/layout";
import { buildGraphData, buildView, type ModuleKind } from "@/lib/graph/model";

const e = (source: string, target: string) => ({ source, target });
const SOURCE: ReadonlySet<ModuleKind> = new Set(["source"]);

function project() {
  const edges = [
    e("app.main", "app.auth.routes"),
    e("app.auth.routes", "app.auth.service"),
    e("app.auth.service", "app.db.session"),
    e("app.auth.routes", "app.db.session"),
    e("app.db.session", "app.auth.service"),
  ];
  return buildGraphData({ nodes: [], edges });
}

describe("computeLayout (ELK layered)", () => {
  it("places every node, keeps children inside their folder box, and flows top to bottom", async () => {
    const view = buildView(project(), { expanded: new Set(["app", "app.auth"]), kinds: SOURCE });
    const out = await computeLayout(new ELK(), view);
    for (const n of view.nodes) expect(out.positions[n.id], n.id).toBeDefined();
    const box = out.positions["g:app.auth"];
    for (const id of ["m:app.auth.routes", "m:app.auth.service"]) {
      const p = out.positions[id];
      expect(p.x).toBeGreaterThanOrEqual(0);
      expect(p.y).toBeGreaterThanOrEqual(0);
      expect(p.x + p.width).toBeLessThanOrEqual(box.width);
      expect(p.y + p.height).toBeLessThanOrEqual(box.height);
    }
    // main depends on auth, so it is drawn above it
    expect(out.positions["m:app.main"].y).toBeLessThan(out.positions["g:app.auth"].y);
  });

  it("gives the same picture for the same repository however the input is ordered", async () => {
    const a = buildView(project(), { expanded: new Set(["app"]), kinds: SOURCE });
    const shuffled = buildGraphData({ nodes: [], edges: [...project().edges].reverse() });
    const b = buildView(shuffled, { expanded: new Set(["app"]), kinds: SOURCE });
    const [ra, rb] = [await computeLayout(new ELK(), a), await computeLayout(new ELK(), b)];
    expect(rb).toEqual(ra);
  });

  it("lays out an empty view without calling the engine", async () => {
    const out = await computeLayout({ layout: () => Promise.reject(new Error("should not run")) }, { nodes: [], edges: [], includedModules: 0, excludedByKind: 0, unconnected: 0, hubs: [], hubEdges: [] });
    expect(out.positions).toEqual({});
  });

  it("copes with a few hundred modules in reasonable time", async () => {
    const nodes = Array.from({ length: 400 }, (_, i) => `pkg${i % 8}.m${i}`);
    const edges = nodes.flatMap((n, i) => [e(n, nodes[(i * 7 + 3) % 400]), e(n, nodes[(i * 13 + 5) % 400])]).filter((x) => x.source !== x.target);
    const d = buildGraphData({ nodes, edges });
    const view = buildView(d, { expanded: new Set(d.rootGroups), kinds: SOURCE, limits: new Map(d.rootGroups.map((g) => [g, 60])) });
    const t = Date.now();
    const out = await computeLayout(new ELK(), view);
    expect(Object.keys(out.positions).length).toBe(view.nodes.length);
    expect(Date.now() - t).toBeLessThan(15000);
  });
});
