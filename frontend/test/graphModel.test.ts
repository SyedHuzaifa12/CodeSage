import { describe, expect, it } from "vitest";
import {
  buildGraphModel,
  buildModuleIndex,
  classifyRisk,
  cycleEdgeKeys,
  fileToModule,
  flattenTreeFiles,
  isFolderNode,
  moduleAreas,
  nodeLabel,
  sharedPrefixDepth,
} from "@/lib/graphModel";
import type { TreeNode } from "@/lib/types/workspace";

describe("fileToModule", () => {
  it("mirrors the backend's module_path_from_relative_path", () => {
    expect(fileToModule("app/auth/routes.py")).toBe("app.auth.routes");
    expect(fileToModule("src/lib/a.test.ts")).toBe("src.lib.a.test");
    expect(fileToModule("Makefile")).toBe("Makefile");
    expect(fileToModule("v1.2/readme")).toBe("v1.2.readme");
  });
});

describe("tree helpers", () => {
  const tree = [
    { name: "app", path: "app", type: "folder", children: [{ name: "main.py", path: "app/main.py", type: "file" }] },
    { name: "setup.py", path: "setup.py", type: "file" },
  ] as unknown as TreeNode[];

  it("treats the backend's 'folder' type as a folder", () => {
    expect(isFolderNode(tree[0])).toBe(true);
    expect(isFolderNode(tree[1])).toBe(false);
  });

  it("flattens to files only and indexes them by module", () => {
    const files = flattenTreeFiles(tree).map((f) => f.path);
    expect(files).toEqual(["app/main.py", "setup.py"]);
    expect(buildModuleIndex(files).get("app.main")).toBe("app/main.py");
  });
});

describe("buildGraphModel", () => {
  const nodes = ["a", "b", "c", "d", "lonely"];
  const edges = [
    { source: "a", target: "b" },
    { source: "a", target: "b" },
    { source: "b", target: "c" },
    { source: "c", target: "a" },
    { source: "d", target: "a" },
    { source: "d", target: "d" },
  ];

  it("dedupes, drops self-loops and computes degrees", () => {
    const m = buildGraphModel(nodes, edges);
    expect(m.edges).toHaveLength(4);
    expect(m.inDegree.get("a")).toBe(2);
    expect(m.outDegree.get("d")).toBe(1);
    expect(m.totalNodes).toBe(5);
  });

  it("caps to the highest-degree nodes and keeps only internal edges", () => {
    const m = buildGraphModel(nodes, edges, { cap: 2 });
    expect(m.nodes).toEqual(["a", "b"]);
    expect(m.edges).toEqual([{ source: "a", target: "b" }]);
    expect(m.allEdges).toHaveLength(4);
  });

  it("filters by module prefix", () => {
    const m = buildGraphModel(["app.x", "app.y", "lib.z"], [
      { source: "app.x", target: "app.y" },
      { source: "app.x", target: "lib.z" },
    ], { prefix: "app" });
    expect(m.nodes.sort()).toEqual(["app.x", "app.y"]);
    expect(m.edges).toHaveLength(1);
  });
});

describe("labels, areas, cycles and risk", () => {
  it("strips the shared prefix from labels", () => {
    const depth = sharedPrefixDepth(["app.api.a", "app.api.b", "app.core"]);
    expect(depth).toBe(1);
    expect(nodeLabel("app.api.a", "dependency", depth)).toBe("api.a");
    expect(nodeLabel("pkg.Cls.method", "call")).toBe("Cls.method");
  });

  it("lists populated module areas", () => {
    expect(moduleAreas(["app.api.a", "app.api.b", "app.core.c", "x"])).toEqual(["app.api"]);
  });

  it("includes the wrap-around edge of every cycle", () => {
    expect([...cycleEdgeKeys([["a", "b", "c"]])]).toEqual(["a→b", "b→c", "c→a"]);
  });

  it("classifies risk with threshold 5 and cycle membership", () => {
    const cycles = [["m", "n"]];
    expect(classifyRisk("m", 5, cycles)).toBe("high");
    expect(classifyRisk("m", 1, cycles)).toBe("medium");
    expect(classifyRisk("z", 5, cycles)).toBe("medium");
    expect(classifyRisk("z", 4, cycles)).toBe("low");
  });
});
