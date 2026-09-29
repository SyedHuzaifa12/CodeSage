"use client";

import { useMemo, useState } from "react";
import { forceLayout, nodeRadius } from "@/lib/forceLayout";
import { buildGraphModel, cycleEdgeKeys, edgeKey, neighborsOf, nodeLabel, sharedPrefixDepth } from "@/lib/graphModel";
import type { GraphEdge } from "@/lib/types/workspace";

/**
 * Overview's repository topology (Design System §17): the real resolved
 * dependency graph, capped to the most connected modules, laid out by a
 * deterministic force layout. Hotspots are ringed in violet, edges that
 * close a detected cycle are red, orphan files are dashed. Every edge is
 * observed — the backend has no "inferred" relationship class.
 */
export function TopologyDiagram({
  nodes,
  edges,
  hotspots,
  cycles = [],
  orphans,
  cap = 24,
  width = 760,
  height = 700,
  onNodeClick,
  layoutKey = "topo",
}: {
  nodes: string[];
  edges: GraphEdge[];
  hotspots?: Set<string>;
  cycles?: string[][];
  orphans?: Set<string>;
  cap?: number;
  width?: number;
  height?: number;
  onNodeClick?: (node: string) => void;
  layoutKey?: string;
}) {
  const [hover, setHover] = useState<string | null>(null);
  const model = useMemo(() => buildGraphModel(nodes, edges, { cap }), [nodes, edges, cap]);
  const positions = useMemo(
    () => forceLayout(model.nodes, model.edges, { width, height, key: layoutKey }),
    [model, width, height, layoutKey],
  );
  const cycleKeys = useMemo(() => cycleEdgeKeys(cycles), [cycles]);
  const prefixDepth = useMemo(() => sharedPrefixDepth(model.nodes), [model.nodes]);

  if (model.nodes.length === 0) {
    return (
      <div className="grid min-h-[220px] place-items-center rounded-[12px] border border-dashed border-border-subtle px-6 py-10 text-center">
        <div>
          <p className="font-mono text-[11.5px] text-text-secondary">No resolved dependencies yet.</p>
          <p className="mx-auto mt-2 max-w-[42ch] text-small text-text-tertiary">
            The topology appears once imports resolve between parsed files. Only Python, JavaScript, TypeScript and Java are parsed.
          </p>
        </div>
      </div>
    );
  }
  const pos = new Map(model.nodes.map((n, i) => [n, positions[i]]));
  const maxDegree = Math.max(1, ...model.nodes.map((n) => model.degree.get(n) ?? 0));
  const rank = new Map([...model.nodes].sort((a, b) => (model.degree.get(b) ?? 0) - (model.degree.get(a) ?? 0)).map((n, i) => [n, i]));
  const near = hover ? neighborsOf(model.edges, hover) : null;
  const hoverPos = hover ? pos.get(hover) : null;

  return (
    <div className="relative w-full">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="block h-auto w-full overflow-visible"
        role="img"
        aria-label={`Dependency topology: ${model.nodes.length} modules shown of ${model.totalNodes}, ${model.edges.length} edges${cycles.length ? `, ${cycles.length} circular dependencies` : ""}. Hotspots ringed in violet; cycle edges in red.`}
      >
        <defs>
          <radialGradient id="cs-tb" cx="35%" cy="30%" r="75%">
            <stop offset="0" stopColor="oklch(0.32 0.014 280)" />
            <stop offset="1" stopColor="oklch(0.2 0.01 280)" />
          </radialGradient>
          <radialGradient id="cs-th" cx="35%" cy="30%" r="75%">
            <stop offset="0" stopColor="oklch(0.46 0.1 300)" />
            <stop offset="1" stopColor="oklch(0.25 0.06 300)" />
          </radialGradient>
          <radialGradient id="cs-tg">
            <stop offset="0" stopColor="oklch(0.75 0.13 300 / 0.35)" />
            <stop offset="1" stopColor="oklch(0.75 0.13 300 / 0)" />
          </radialGradient>
        </defs>
        {model.edges.map((e) => {
          const a = pos.get(e.source)!;
          const b = pos.get(e.target)!;
          const cyc = cycleKeys.has(edgeKey(e));
          const on = hover && (e.source === hover || e.target === hover);
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const dd = Math.hypot(dx, dy) || 1;
          const bend = Math.min(40, dd * 0.12) * (cyc ? 1.6 : 1);
          const mx = (a.x + b.x) / 2 - (dy / dd) * bend;
          const my = (a.y + b.y) / 2 + (dx / dd) * bend;
          return (
            <path
              key={edgeKey(e)}
              d={`M${a.x.toFixed(1)} ${a.y.toFixed(1)} Q${mx.toFixed(1)} ${my.toFixed(1)} ${b.x.toFixed(1)} ${b.y.toFixed(1)}`}
              fill="none"
              stroke={cyc ? "var(--cs-danger)" : on ? "var(--cs-violet-line)" : "oklch(1 0 0 / 0.16)"}
              strokeWidth={cyc ? 1.3 : 1}
              style={{ opacity: hover && !on ? 0.12 : 1, transition: "opacity 200ms, stroke 200ms" }}
            />
          );
        })}
        {model.nodes.map((n) => {
          const p = pos.get(n)!;
          const r = nodeRadius(model.degree.get(n) ?? 0, maxDegree) * 1.15;
          const hot = hotspots?.has(n);
          const orphan = orphans?.has(n);
          const dim = hover && hover !== n && !near?.has(n);
          const label = nodeLabel(n, "dependency", prefixDepth);
          return (
            <g
              key={n}
              role={onNodeClick ? "link" : undefined}
              tabIndex={onNodeClick ? 0 : undefined}
              aria-label={`${n}, ${model.degree.get(n)} connections${hot ? ", dependency hotspot" : ""}${orphan ? ", orphan file" : ""}`}
              onMouseEnter={() => setHover(n)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(n)}
              onBlur={() => setHover(null)}
              onClick={() => onNodeClick?.(n)}
              onKeyDown={(e) => {
                if ((e.key === "Enter" || e.key === " ") && onNodeClick) {
                  e.preventDefault();
                  onNodeClick(n);
                }
              }}
              style={{ cursor: onNodeClick ? "pointer" : undefined, opacity: dim ? 0.18 : 1, transition: "opacity 200ms", outline: "none" }}
            >
              {hot && <circle cx={p.x} cy={p.y} r={r * 2.4} fill="url(#cs-tg)" pointerEvents="none" />}
              {hot && <circle cx={p.x} cy={p.y} r={r + 5} fill="none" stroke="var(--cs-accent-violet)" strokeWidth={1.4} />}
              <circle
                cx={p.x}
                cy={p.y}
                r={r}
                fill={hot ? "url(#cs-th)" : "url(#cs-tb)"}
                stroke={orphan ? "var(--cs-text-tertiary)" : hover === n ? "oklch(1 0 0 / 0.6)" : "oklch(1 0 0 / 0.28)"}
                strokeWidth={1.2}
                strokeDasharray={orphan ? "1.5 2.5" : undefined}
              />
              <text
                x={p.x}
                y={p.y + r + 14}
                textAnchor="middle"
                fontFamily="var(--font-plex-mono)"
                fontSize={(rank.get(n) ?? 99) < 6 ? 11.5 : 10.5}
                fontWeight={(rank.get(n) ?? 99) < 6 ? 500 : 400}
                fill={(rank.get(n) ?? 99) < 6 || hover === n ? "var(--cs-text-primary)" : "var(--cs-text-secondary)"}
                stroke="var(--cs-bg)"
                strokeWidth={3.5}
                paintOrder="stroke"
                strokeLinejoin="round"
                pointerEvents="none"
              >
                {label}
              </text>
            </g>
          );
        })}
      </svg>
      {hover && hoverPos && (
        <div
          className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-[calc(100%+14px)] whitespace-nowrap rounded-[7px] border border-border-strong bg-surface-2 px-2.5 py-1.5 font-mono text-[11px] text-text-primary"
          style={{ left: `${(hoverPos.x / width) * 100}%`, top: `${(hoverPos.y / height) * 100}%` }}
        >
          {hover}
          <br />
          <span className="text-text-tertiary">
            {model.inDegree.get(hover)} incoming · {model.outDegree.get(hover)} outgoing{hotspots?.has(hover) ? " · hotspot" : ""}
          </span>
        </div>
      )}
    </div>
  );
}
