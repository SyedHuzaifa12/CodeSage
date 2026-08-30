"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useRepositoryContext } from "@/context/RepositoryContext";
import { RequireReady } from "@/components/nav/RequireReady";
import { GraphCanvas } from "@/components/graph/GraphCanvas";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { SkeletonBlock } from "@/components/state/Loading";
import { ErrorPanel } from "@/components/state/StateVocabulary";
import { useCallGraph, useDependencyGraph, useIntelligence, useSymbols } from "@/lib/query/workspace";
import { capGraphByConnectivity, DEFAULT_GRAPH_NODE_CAP } from "@/lib/graphCap";
import { ApiError } from "@/lib/api/client";
import { TopologyDiagram } from "@/components/domain/TopologyDiagram";
import { useBreakpoint } from "@/hooks/useMediaQuery";

type GraphMode = "dependency" | "call";

function GraphInner() {
  const { repositoryId } = useRepositoryContext();
  const router = useRouter();
  const breakpoint = useBreakpoint();
  const [mode, setMode] = useState<GraphMode>("dependency");
  const [focusedNode, setFocusedNode] = useState<string | null>(null);

  const depGraph = useDependencyGraph(repositoryId, { enabled: mode === "dependency" });
  const callGraph = useCallGraph(repositoryId, { enabled: mode === "call" });
  const intelligence = useIntelligence(repositoryId);
  const symbols = useSymbols(repositoryId);

  const active = mode === "dependency" ? depGraph : callGraph;
  const hotspotFiles = new Set((intelligence.data?.dependency_hotspots ?? []).map((h) => h.module_path));

  const capped = useMemo(() => {
    if (!active.data) return null;
    return capGraphByConnectivity(active.data.nodes, active.data.edges, DEFAULT_GRAPH_NODE_CAP);
  }, [active.data]);

  const focusedSymbols = focusedNode ? symbols.data?.symbols.filter((s) => s.file_path === focusedNode) ?? [] : [];
  const focusedDegree = focusedNode ? capped?.degreeByNode.get(focusedNode) ?? 0 : 0;

  if (breakpoint === "mobile") {
    return (
      <div className="flex flex-col gap-4 px-6 py-8">
        <h1 className="font-display text-[22px] italic text-text-primary">Knowledge map</h1>
        <p className="text-small text-text-secondary">
          The interactive graph is best explored on a larger screen. Here&rsquo;s a static preview —
          open CodeSage on a tablet or desktop for full pan/zoom exploration.
        </p>
        <div className="h-[260px] cs-card p-4">
          {capped && capped.nodes.length > 0 && (
            <TopologyDiagram nodes={capped.nodes} edges={capped.edges} hotspotFiles={hotspotFiles} />
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="relative flex h-[calc(100vh-56px)]">
      <div className="relative flex flex-1 flex-col">
        <div className="flex items-baseline justify-between px-11 pt-5">
          <div className="flex items-baseline gap-3.5">
            <h1 className="font-display text-[24px] italic text-text-primary">Knowledge map</h1>
            <SegmentedControl
              aria-label="Graph type"
              value={mode}
              onChange={setMode}
              options={[
                { value: "dependency", label: "Dependency" },
                { value: "call", label: "Call graph" },
              ]}
            />
          </div>
          {capped && (
            <div className="font-mono text-[10.5px] text-text-tertiary">
              top {capped.nodes.length} of {capped.totalNodes} modules &middot; sized by connectivity
            </div>
          )}
        </div>

        <div className="min-h-0 flex-1 px-2">
          {active.isLoading && <SkeletonBlock className="m-9 h-full" />}
          {active.isError && (
            <ErrorPanel className="m-9" message={active.error instanceof ApiError ? active.error.message : "Couldn't load the graph."} />
          )}
          {capped && capped.nodes.length > 0 && (
            <GraphCanvas
              nodes={capped.nodes}
              edges={capped.edges}
              hotspotFiles={hotspotFiles}
              focusedNode={focusedNode}
              onNodeClick={setFocusedNode}
            />
          )}
          {capped && capped.nodes.length === 0 && (
            <div className="flex h-full items-center justify-center font-mono text-[11px] text-text-tertiary">
              No resolved relationships yet for this graph type.
            </div>
          )}
        </div>

        <div className="flex items-center gap-4 px-11 pb-5 pt-1.5 font-mono text-[10px] text-text-tertiary">
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-px w-3.5 bg-[oklch(0.4_0.02_280)]" /> observed dependency
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-full border-[1.5px] border-violet" /> hotspot
          </span>
        </div>
        <p className="sr-only" role="status">
          {capped
            ? `Graph: ${capped.nodes.length} nodes shown of ${capped.totalNodes} total, ${capped.edges.length} edges.`
            : "Loading graph."}
        </p>
      </div>

      <div className="hidden w-[260px] flex-shrink-0 flex-col gap-4 border-l border-border-subtle px-8 py-6 lg:flex">
        {!focusedNode && <p className="text-small text-text-tertiary">Select a node to inspect its symbols.</p>}
        {focusedNode && (
          <>
            <div>
              <div className="font-display text-[17px] italic text-text-primary">{focusedNode}</div>
              <div className="mt-1.5 font-mono text-[10px] text-text-tertiary">
                {focusedDegree} connection{focusedDegree === 1 ? "" : "s"} &middot; {focusedSymbols.length} symbols
              </div>
            </div>
            <div className="flex flex-col">
              {focusedSymbols.slice(0, 20).map((sym) => (
                <div key={sym.id} className="border-b border-border-subtle py-2 font-mono text-[11.5px] text-text-secondary">
                  {sym.name}
                </div>
              ))}
            </div>
            <button
              onClick={() => router.push(`/r/${repositoryId}/ask?q=${encodeURIComponent(`Explain ${focusedNode}`)}`)}
              className="mt-auto w-fit font-mono text-[10.5px] text-violet hover:underline"
            >
              ask about this node &rarr;
            </button>
          </>
        )}
      </div>
    </div>
  );
}

export default function GraphPage() {
  return (
    <RequireReady>
      <GraphInner />
    </RequireReady>
  );
}
