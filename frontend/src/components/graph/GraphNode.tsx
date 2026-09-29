"use client";

import { BaseEdge, Handle, Position, type EdgeProps, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/utils";

export interface CsGraphNodeData extends Record<string, unknown> {
  id: string;
  label: string;
  radius: number;
  inDegree: number;
  outDegree: number;
  hotspot: boolean;
  orphan: boolean;
  selected: boolean;
  dim: boolean;
  hub: boolean;
  onActivate: (id: string) => void;
  onHover: (id: string | null) => void;
}

export const NODE_WIDTH = 160;

/**
 * Knowledge-map node: a sphere sized by connectivity (radial gradient,
 * no shadow), a violet ring + glow for hotspots, a dashed outline for
 * orphan files, a double ring when selected. Invisible handles sit at the
 * sphere's centre so edges can be trimmed to its boundary.
 */
export function CsGraphNode({ data }: NodeProps) {
  const d = data as CsGraphNodeData;
  const r = d.radius;
  const size = r * 2;
  const handleStyle = { top: r + 10, left: "50%", opacity: 0, width: 1, height: 1, minWidth: 0, minHeight: 0, border: 0, transform: "translate(-50%,-50%)" };
  return (
    <div
      className="flex flex-col items-center outline-none"
      style={{ width: NODE_WIDTH, opacity: d.dim ? 0.14 : 1, transition: "opacity 200ms" }}
      role="button"
      tabIndex={0}
      aria-pressed={d.selected}
      aria-label={`${d.id}: ${d.inDegree} incoming, ${d.outDegree} outgoing${d.hotspot ? ", hotspot" : ""}${d.orphan ? ", orphan file" : ""}`}
      data-graph-node={d.id}
      onMouseEnter={() => d.onHover(d.id)}
      onMouseLeave={() => d.onHover(null)}
      onFocus={() => d.onHover(d.id)}
      onBlur={() => d.onHover(null)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          d.onActivate(d.id);
        }
      }}
    >
      <Handle type="target" position={Position.Top} style={handleStyle} isConnectable={false} />
      <div className="relative mt-[10px]" style={{ width: size, height: size }}>
        {d.hotspot && (
          <span
            className="pointer-events-none absolute rounded-full"
            style={{ inset: -r * 1.3, background: "radial-gradient(closest-side, oklch(0.75 0.13 300 / 0.32), transparent)" }}
            aria-hidden="true"
          />
        )}
        {(d.hotspot || d.selected) && (
          <span
            className={cn("pointer-events-none absolute rounded-full border-[1.5px]", d.selected ? "border-violet" : "border-violet/90")}
            style={{ inset: d.selected ? -9 : -5 }}
            aria-hidden="true"
          />
        )}
        <span
          className="cs-gnode-body absolute inset-0 rounded-full border transition-[background] duration-standard"
          style={{
            background: d.selected
              ? "radial-gradient(circle at 35% 30%, oklch(0.88 0.09 300), oklch(0.66 0.14 300))"
              : d.hotspot
                ? "radial-gradient(circle at 35% 30%, oklch(0.46 0.1 300), oklch(0.25 0.06 300))"
                : "radial-gradient(circle at 35% 30%, oklch(0.32 0.014 280), oklch(0.2 0.01 280))",
            borderColor: d.orphan ? "var(--cs-text-tertiary)" : "oklch(1 0 0 / 0.3)",
            borderStyle: d.orphan ? "dashed" : "solid",
          }}
          aria-hidden="true"
        />
      </div>
      <span
        className={cn(
          "mt-1.5 max-w-full truncate px-1 font-mono",
          d.hub ? "text-[11.5px] font-medium text-text-primary" : "text-[10.5px] text-text-secondary",
          d.selected && "text-[var(--cs-accent-violet-hover)]",
        )}
        style={{ textShadow: "0 0 3px var(--cs-bg), 0 0 6px var(--cs-bg)" }}
      >
        {d.label}
      </span>
      <Handle type="source" position={Position.Bottom} style={handleStyle} isConnectable={false} />
    </div>
  );
}

export interface CsGraphEdgeData extends Record<string, unknown> {
  sourceRadius: number;
  targetRadius: number;
  cycle: boolean;
  active: boolean;
  dim: boolean;
  bend: number;
}

/** Curved edge trimmed to both spheres' boundaries so the arrowhead stays visible. */
export function CsGraphEdge({ id, sourceX, sourceY, targetX, targetY, data, markerEnd }: EdgeProps) {
  const d = data as CsGraphEdgeData;
  const dx = targetX - sourceX;
  const dy = targetY - sourceY;
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len;
  const uy = dy / len;
  const sx = sourceX + ux * (d.sourceRadius + 2);
  const sy = sourceY + uy * (d.sourceRadius + 2);
  const tx = targetX - ux * (d.targetRadius + 5);
  const ty = targetY - uy * (d.targetRadius + 5);
  const mx = (sx + tx) / 2 - uy * d.bend;
  const my = (sy + ty) / 2 + ux * d.bend;
  const stroke = d.cycle ? "var(--cs-danger)" : d.active ? "var(--cs-accent-violet)" : "oklch(1 0 0 / 0.2)";
  return (
    <BaseEdge
      id={id}
      path={`M${sx} ${sy} Q${mx} ${my} ${tx} ${ty}`}
      markerEnd={markerEnd}
      style={{
        stroke,
        strokeWidth: d.cycle ? 1.5 : d.active ? 1.4 : 1.1,
        opacity: d.dim ? 0.1 : 1,
        transition: "opacity 200ms, stroke 200ms",
        ...(d.active ? { strokeDasharray: "5 4", animation: "cs-flow 1.1s linear infinite" } : {}),
      }}
    />
  );
}
