"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/utils";

export interface CsGraphNodeData extends Record<string, unknown> {
  label: string;
  degree: number;
  maxDegree: number;
  isHotspot: boolean;
  focused: boolean;
}

/** Centrality-sized graph node (Design System §17): root/hub nodes visibly larger, focused node gets a double ring. */
export function CsGraphNode({ data, selected }: NodeProps) {
  const nodeData = data as CsGraphNodeData;
  const ratio = nodeData.maxDegree > 0 ? nodeData.degree / nodeData.maxDegree : 0;
  const size = 10 + ratio * 22;

  return (
    <div
      className="flex flex-col items-center gap-1 focus:outline-none"
      style={{ width: size + 60 }}
      role="button"
      tabIndex={0}
      aria-label={`${nodeData.label}, ${nodeData.degree} connections${nodeData.isHotspot ? ", hotspot" : ""}`}
    >
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <div className="relative flex items-center justify-center" style={{ width: size + 16, height: size + 16 }}>
        {(selected || nodeData.focused) && (
          <span
            className="absolute rounded-full border border-violet/30"
            style={{ width: size + 16, height: size + 16 }}
          />
        )}
        <span
          className={cn("rounded-full", ratio > 0.5 ? "bg-violet" : "border-[1.8px] border-violet")}
          style={{ width: size, height: size, background: ratio > 0.5 ? undefined : "transparent" }}
        />
      </div>
      <span className="max-w-[140px] truncate font-mono text-[11px] text-text-primary/90">{nodeData.label}</span>
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
    </div>
  );
}
