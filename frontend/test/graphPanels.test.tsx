import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GraphKey, GraphSummary } from "@/components/graph/GraphPanels";
import { ModuleTable } from "@/components/graph/ModuleTable";
import { buildGraphData, findTangles, tangleIndex, type ModuleKind } from "@/lib/graph/model";

afterEach(cleanup);

const e = (source: string, target: string) => ({ source, target });
const SOURCE: ReadonlySet<ModuleKind> = new Set(["source"]);
const data = () =>
  buildGraphData({
    nodes: ["app.lonely"],
    edges: [e("app.a", "app.core"), e("app.b", "app.core"), e("app.core", "app.a"), e("app.c", "app.core")],
  });

describe("ModuleTable", () => {
  const setup = (query = "") => {
    const d = data();
    const onSelect = vi.fn();
    render(<ModuleTable data={d} kinds={SOURCE} query={query} selected={null} tangleOf={tangleIndex(findTangles(d))} hotspots={new Set()} entries={new Set(["app.c"])} unit="module" onSelect={onSelect} />);
    return { onSelect, ids: () => screen.getAllByRole("row").slice(1).map((r) => within(r).getAllByRole("button")[0].textContent) };
  };

  it("lists the most depended-on module first, and says which have no connections", () => {
    const { ids } = setup();
    expect(ids()[0]).toBe("app.core");
    expect(screen.getAllByText("standalone").length).toBeGreaterThan(0);
  });

  it("sorts by a column and reverses on a second click", () => {
    const { ids } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Module" }));
    expect(ids()[0]).toBe("app.a");
    fireEvent.click(screen.getByRole("button", { name: "Module" }));
    expect(ids()[0]).toBe("app.lonely");
  });

  it("filters by what is typed and reports the count", () => {
    const { ids } = setup("core");
    expect(ids()).toEqual(["app.core"]);
    expect(screen.getAllByRole("status")[0].textContent).toContain('1 module matching "core"');
  });

  it("selects a row, and marks entry points and loops in words (not only colour)", () => {
    const { onSelect } = setup();
    fireEvent.click(screen.getAllByRole("button", { name: "app.c" })[0]);
    expect(onSelect).toHaveBeenCalledWith("app.c");
    expect(screen.getAllByText("entry point").length).toBeGreaterThan(0);
    expect(screen.getAllByText("in a loop").length).toBeGreaterThan(0);
  });
});

describe("GraphSummary", () => {
  it("explains the picture, ranks key modules and describes loops and what is not drawn", () => {
    const d = data();
    const onPick = vi.fn();
    render(
      <GraphSummary kind="dependency" data={d} kinds={SOURCE} tangles={findTangles(d)} entries={[]} unconnected={165} hidden={{ tests: 12, external: 3 }} onPick={onPick} onShowList={vi.fn()} />,
    );
    expect(screen.getByText(/An arrow from A to B means A imports B/)).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: /app\.core/ })[0]);
    expect(onPick).toHaveBeenCalledWith("app.core");
    expect(screen.getByText("2 modules")).toBeTruthy();
    expect(screen.getByText(/165 standalone modules/)).toBeTruthy();
    expect(screen.getByText(/12 test or example files/)).toBeTruthy();
    expect(screen.getByText(/3 outside packages/)).toBeTruthy();
  });

  it("says plainly when there are no circular dependencies", () => {
    const d = buildGraphData({ nodes: [], edges: [e("a.x", "a.y")] });
    render(<GraphSummary kind="dependency" data={d} kinds={SOURCE} tangles={[]} entries={[]} unconnected={0} hidden={{ tests: 0, external: 0 }} onPick={vi.fn()} onShowList={vi.fn()} />);
    expect(screen.getByText(/None found/)).toBeTruthy();
  });
});

describe("GraphKey", () => {
  it("only lists the loop marker when the repository has loops", () => {
    const { rerender } = render(<GraphKey kind="dependency" hasTangles={false} />);
    expect(screen.queryByText(/circular/)).toBeNull();
    rerender(<GraphKey kind="dependency" hasTangles />);
    expect(screen.getByText(/circular/)).toBeTruthy();
  });
});
