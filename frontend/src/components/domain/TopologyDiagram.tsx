"use client";

import { computeRadialLayout } from "@/lib/radialLayout";
import type { GraphEdge } from "@/lib/types/workspace";

/**
 * Overview's large annotated topology diagram (Design System §17): the
 * dominant visual on the page, ported in spirit from Main.dc.html's
 * "REPOSITORY TOPOLOGY" panel — radial layout, violet root/hub nodes,
 * mono file labels, an annotated leader-line callout for the hotspot
 * count. Built from REAL /call-graph or /dependency-graph data — never
 * placeholder nodes.
 */
export function TopologyDiagram({
  nodes,
  edges,
  hotspotCount,
  hotspotFiles,
  onNodeClick,
}: {
  nodes: string[];
  edges: GraphEdge[];
  hotspotCount?: number;
  hotspotFiles?: Set<string>;
  onNodeClick?: (node: string) => void;
}) {
  const layout = computeRadialLayout(nodes, edges);

  if (layout.nodes.length === 0) {
    return (
      <div className="flex h-full items-center justify-center font-mono text-[11px] text-text-tertiary">
        No resolved dependencies yet.
      </div>
    );
  }

  const calloutNode = layout.nodes.find((n) => n.ring === 1) ?? layout.nodes[0];

  return (
    <svg
      width="100%"
      height="100%"
      viewBox={`0 0 ${layout.width} ${layout.height}`}
      role="img"
      aria-label={`Dependency topology: ${layout.nodes.length} of ${nodes.length} modules shown, ${layout.edges.length} dependencies, ${hotspotCount ?? 0} hotspots.`}
    >
      <circle cx={layout.width / 2} cy={layout.height / 2} r={120} fill="none" stroke="oklch(1 0 0 / 0.035)" />
      <circle cx={layout.width / 2} cy={layout.height / 2} r={210} fill="none" stroke="oklch(1 0 0 / 0.025)" />

      <g strokeWidth={1.2} fill="none">
        {layout.edges.map((edge, i) => {
          const a = layout.nodes.find((n) => n.id === edge.source);
          const b = layout.nodes.find((n) => n.id === edge.target);
          if (!a || !b) return null;
          const strong = a.ring === 0 || b.ring === 0;
          return (
            <line
              key={i}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              stroke={strong ? "oklch(0.42 0.02 280)" : "oklch(0.34 0.02 280)"}
              strokeWidth={strong ? 2 : 1}
            />
          );
        })}
      </g>

      <g fontFamily="var(--font-plex-mono)" fontSize={12} fill="oklch(0.88 0.006 280)">
        {layout.nodes.map((node) => {
          const isHotspot = hotspotFiles?.has(node.id);
          const label = node.id.length > 24 ? `…${node.id.slice(-22)}` : node.id;
          const radius = node.ring === 0 ? 9 : node.ring === 1 ? 8 : 4.5;
          return (
            <g
              key={node.id}
              onClick={onNodeClick ? () => onNodeClick(node.id) : undefined}
              style={onNodeClick ? { cursor: "pointer" } : undefined}
            >
              <circle
                cx={node.x}
                cy={node.y}
                r={radius}
                fill={node.ring === 0 ? "oklch(0.85 0.13 300)" : node.ring === 1 ? "none" : "oklch(0.58 0.02 280)"}
                stroke={node.ring <= 1 ? "oklch(0.85 0.13 300)" : undefined}
                strokeWidth={node.ring === 1 ? 1.8 : undefined}
              />
              {isHotspot && node.ring === 1 && (
                <circle cx={node.x} cy={node.y} r={radius + 7} fill="none" stroke="oklch(0.75 0.13 300 / 0.25)" strokeWidth={1} />
              )}
              <text x={node.x + radius + 6} y={node.y + 4} fill={node.ring === 2 ? "oklch(0.6 0.01 280)" : undefined}>
                {label}
              </text>
            </g>
          );
        })}
      </g>

      {hotspotCount !== undefined && hotspotCount > 0 && (
        <>
          <line
            x1={calloutNode.x + 8}
            y1={calloutNode.y - 8}
            x2={calloutNode.x + 90}
            y2={calloutNode.y - 60}
            stroke="oklch(0.55 0.01 280 / 0.4)"
            strokeWidth={1}
          />
          <text
            x={calloutNode.x + 94}
            y={calloutNode.y - 57}
            fontFamily="var(--font-newsreader)"
            fontStyle="italic"
            fontSize={13}
            fill="oklch(0.8 0.01 280)"
          >
            {hotspotCount} hotspot{hotspotCount === 1 ? "" : "s"}
          </text>
        </>
      )}
    </svg>
  );
}
