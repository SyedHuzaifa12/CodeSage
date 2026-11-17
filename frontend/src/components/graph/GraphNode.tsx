"use client";

import { BaseEdge, EdgeLabelRenderer, Handle, Position, getBezierPath, type EdgeProps, type NodeProps } from "@xyflow/react";
import { ChevronDown, ChevronRight, Flame, Folder, FolderOpen, LogIn, Plus, RotateCw } from "lucide-react";
import type { ModuleKind } from "@/lib/graph/model";
import { cn } from "@/lib/utils";

/** How a drawn box relates to the module that is selected: it is imported by it, or it imports it. */
export type Relation = "imports" | "importedBy" | null;

const hidden = { opacity: 0, width: 1, height: 1, minWidth: 0, minHeight: 0, border: 0 } as const;
function Handles() {
  return (
    <>
      <Handle type="target" position={Position.Top} style={hidden} isConnectable={false} />
      <Handle type="source" position={Position.Bottom} style={hidden} isConnectable={false} />
    </>
  );
}

/** Dimmed boxes stay readable (this is a map, not a spotlight) but clearly recede. */
const dimStyle = (dim: boolean) => ({ opacity: dim ? 0.32 : 1, transition: "opacity 160ms" });

// ---------------------------------------------------------------------------------------------------------------------

export interface ModuleNodeData extends Record<string, unknown> {
  moduleId: string;
  label: string;
  kind: ModuleKind;
  /** How many other modules import this one. */
  usedBy: number;
  hotspot: boolean;
  entry: boolean;
  tangled: boolean;
  selected: boolean;
  relation: Relation;
  dim: boolean;
  onSelect: (moduleId: string) => void;
}

const KIND_NOTE: Record<ModuleKind, string> = { source: "", test: "test file", example: "example file", external: "external package" };

export function ModuleNode({ data }: NodeProps) {
  const d = data as ModuleNodeData;
  const notes = [
    d.entry && "entry point",
    d.hotspot && "hotspot, many modules depend on it",
    d.tangled && "part of a circular dependency",
    KIND_NOTE[d.kind],
    d.relation === "imports" && "imported by the selected module",
    d.relation === "importedBy" && "imports the selected module",
  ].filter(Boolean);
  return (
    <button
      type="button"
      data-graph-node={d.moduleId}
      aria-pressed={d.selected}
      aria-label={`${d.moduleId}. Used by ${d.usedBy} modules.${notes.length ? ` ${notes.join(", ")}.` : ""}`}
      title={d.moduleId}
      onClick={(e) => {
        e.stopPropagation();
        d.onSelect(d.moduleId);
      }}
      className={cn(
        "flex h-full w-full items-center gap-1.5 rounded-md border bg-surface-1 px-2.5 text-left font-mono text-[12px] leading-none text-text-primary outline-none transition-colors",
        "hover:border-border-strong hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-violet",
        d.kind === "external" ? "border-dashed border-border-strong text-text-secondary" : "border-border-subtle",
        d.kind === "test" && "text-text-secondary",
        d.hotspot && "border-[1.5px] border-violet",
        d.relation === "imports" && "border-[1.5px] border-violet bg-[var(--cs-violet-tint)]",
        d.relation === "importedBy" && "border-[1.5px] border-cyan bg-[var(--cs-cyan-tint)]",
        d.selected && "border-2 border-violet bg-[var(--cs-violet-tint)] shadow-[0_0_0_3px_var(--cs-violet-tint)]",
      )}
      style={dimStyle(d.dim)}
    >
      <Handles />
      {d.entry && <LogIn size={12} className="flex-none text-info" aria-hidden="true" />}
      {d.hotspot && <Flame size={12} className="flex-none text-violet" aria-hidden="true" />}
      <span className="min-w-0 flex-1 truncate">{d.label}</span>
      {d.tangled && <RotateCw size={11} className="flex-none text-danger" aria-hidden="true" />}
      {d.usedBy > 0 && <span className="flex-none rounded bg-surface-3 px-1 py-[2px] text-[10px] text-text-tertiary">{d.usedBy}</span>}
    </button>
  );
}

// ---------------------------------------------------------------------------------------------------------------------

export interface GroupNodeData extends Record<string, unknown> {
  groupId: string;
  label: string;
  expanded: boolean;
  moduleCount: number;
  dim: boolean;
  onToggle: (groupId: string) => void;
}

/**
 * A folder. Closed, it is a card that stands for everything inside it ("click to open"); open, it is a labelled box
 * around its contents, and its header closes it again.
 */
export function GroupNode({ data }: NodeProps) {
  const d = data as GroupNodeData;
  const verb = d.expanded ? "Collapse" : "Expand";
  return (
    <div
      className={cn("h-full w-full rounded-lg border", d.expanded ? "border-dashed border-border-strong bg-[oklch(var(--cs-ov)_0_0/0.025)]" : "border-border-strong bg-surface-1 shadow-[var(--cs-card-highlight)]")}
      style={dimStyle(d.dim)}
    >
      <Handles />
      <button
        type="button"
        aria-expanded={d.expanded}
        aria-label={`${verb} folder ${d.label}, ${d.moduleCount} modules`}
        title={`${verb} ${d.groupId}`}
        data-graph-group={d.groupId}
        onClick={(e) => {
          e.stopPropagation();
          d.onToggle(d.groupId);
        }}
        className={cn(
          "flex w-full items-center gap-2 text-left outline-none focus-visible:ring-2 focus-visible:ring-violet",
          d.expanded ? "h-[34px] rounded-t-lg px-3 hover:bg-[oklch(var(--cs-ov)_0_0/0.04)]" : "h-full rounded-lg px-3.5 hover:bg-surface-2",
        )}
      >
        {d.expanded ? <FolderOpen size={15} className="flex-none text-text-tertiary" aria-hidden="true" /> : <Folder size={16} className="flex-none text-violet" aria-hidden="true" />}
        <span className="min-w-0 flex-1">
          <span className={cn("block truncate font-mono", d.expanded ? "text-[12px] font-medium text-text-secondary" : "text-[13px] font-medium text-text-primary")}>{d.label}</span>
          {!d.expanded && <span className="mt-1 block text-[11px] text-text-tertiary">{d.moduleCount.toLocaleString("en-US")} {d.moduleCount === 1 ? "module" : "modules"}</span>}
        </span>
        {d.expanded ? <ChevronDown size={14} className="flex-none text-text-tertiary" aria-hidden="true" /> : <ChevronRight size={14} className="flex-none text-text-tertiary" aria-hidden="true" />}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------------

export interface MoreNodeData extends Record<string, unknown> {
  groupId: string;
  hidden: number;
  dim: boolean;
  onMore: (groupId: string) => void;
}

/** The modules of a crowded folder that are not drawn one by one. Never silent: it says how many, and opens them. */
export function MoreNode({ data }: NodeProps) {
  const d = data as MoreNodeData;
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        d.onMore(d.groupId);
      }}
      aria-label={`Show ${d.hidden} more modules`}
      className="flex h-full w-full items-center justify-center gap-1 rounded-md border border-dashed border-border-strong bg-surface-1 font-mono text-[12px] text-text-secondary outline-none hover:bg-surface-2 hover:text-text-primary focus-visible:ring-2 focus-visible:ring-violet"
      style={dimStyle(d.dim)}
    >
      <Handles />
      <Plus size={12} aria-hidden="true" />
      {d.hidden.toLocaleString("en-US")} more
    </button>
  );
}

// ---------------------------------------------------------------------------------------------------------------------

export interface AggregateEdgeData extends Record<string, unknown> {
  weight: number;
  tangled: boolean;
  /** "out" leaves the selected box, "in" arrives at it. */
  direction: "out" | "in" | null;
  dim: boolean;
  /** Show the "×N" count even when not highlighted (only sensible on a small picture). */
  showCount: boolean;
}

/**
 * One drawn edge, standing for every import between its two ends. Thickness grows with how many there are (the count is
 * also written as text, so it never depends on judging thickness), and the style carries the meaning without colour:
 * dashed red for an edge inside a circular dependency, solid violet for what the selection imports, cyan for what
 * imports it.
 */
export function AggregateEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, markerEnd }: EdgeProps) {
  const d = data as AggregateEdgeData;
  const [path, lx, ly] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, curvature: 0.35 });
  const active = d.direction !== null;
  const stroke = d.tangled ? "var(--cs-danger)" : d.direction === "in" ? "var(--cs-accent-cyan)" : active ? "var(--cs-accent-violet)" : "oklch(var(--cs-ov) 0 0 / 0.34)";
  const width = Math.min(4, 1 + Math.log2(d.weight) * 0.7) + (active ? 0.5 : 0);
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        style={{
          stroke,
          strokeWidth: width,
          strokeDasharray: d.tangled ? "5 4" : undefined,
          opacity: d.dim ? 0.1 : 1,
          transition: "opacity 160ms",
        }}
      />
      {d.weight > 1 && (active || d.showCount) && !d.dim && (
        <EdgeLabelRenderer>
          <span
            className="pointer-events-none absolute rounded-full border border-border-subtle bg-surface-1 px-1.5 py-[1px] font-mono text-[10px] text-text-secondary"
            style={{ transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)` }}
            title={`${d.weight} imports`}
          >
            ×{d.weight}
          </span>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
