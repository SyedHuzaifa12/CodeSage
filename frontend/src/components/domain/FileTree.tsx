"use client";

import { ChevronRight, File, Folder } from "lucide-react";
import { isFolderNode } from "@/lib/graphModel";
import type { TreeNode } from "@/lib/types/workspace";
import { cn } from "@/lib/utils";

export type FileMarker = "entry" | "hotspot" | "orphan";

const MARKER_CLASS: Record<FileMarker, string> = {
  entry: "bg-cyan",
  hotspot: "bg-violet",
  orphan: "border border-dotted border-text-tertiary",
};

function formatSize(b?: number | null): string {
  if (b == null) return "";
  if (b >= 1e6) return `${(b / 1e6).toFixed(1)} MB`;
  if (b >= 1e3) return `${(b / 1e3).toFixed(1)} KB`;
  return `${b} B`;
}

/**
 * Controlled file tree over GET /tree. The backend emits `type: "folder"`
 * (the Sprint 7 tree only recognised `"directory"`, so no folder could be
 * expanded) — `isFolderNode` accepts both.
 */
export function FileTree({
  nodes,
  expanded,
  onToggle,
  onSelect,
  selectedPath,
  markers,
  depth = 0,
}: {
  nodes: TreeNode[];
  expanded: Set<string>;
  onToggle: (path: string) => void;
  onSelect: (node: TreeNode) => void;
  selectedPath: string | null;
  markers?: Map<string, FileMarker>;
  depth?: number;
}) {
  return (
    <ul
      role={depth === 0 ? "tree" : "group"}
      aria-label={depth === 0 ? "File tree" : undefined}
      className={cn("m-0 list-none p-0", depth > 0 && "ml-[9px] border-l border-border-subtle pl-2.5")}
    >
      {nodes.map((node) => {
        const folder = isFolderNode(node);
        const open = folder && expanded.has(node.path);
        const marker = markers?.get(node.path);
        return (
          <li key={node.path} role="treeitem" aria-expanded={folder ? open : undefined} aria-selected={!folder ? node.path === selectedPath : undefined}>
            <button
              onClick={() => (folder ? onToggle(node.path) : onSelect(node))}
              aria-current={!folder && node.path === selectedPath ? "true" : undefined}
              className={cn(
                "flex min-h-[28px] w-full items-center gap-[7px] rounded-[6px] px-2 py-[3px] text-left font-mono text-[12.5px] transition-colors",
                !folder && node.path === selectedPath
                  ? "bg-[linear-gradient(90deg,var(--cs-violet-tint),oklch(0.75_0.13_300/0.03))] text-text-primary shadow-[inset_2px_0_0_var(--cs-accent-violet)]"
                  : "text-text-secondary hover:bg-surface-1 hover:text-text-primary",
              )}
            >
              {folder ? (
                <ChevronRight size={13} className={cn("flex-none text-text-tertiary transition-transform duration-standard", open && "rotate-90")} aria-hidden="true" />
              ) : (
                <span className="w-[13px] flex-none" />
              )}
              {folder ? (
                <Folder size={13} strokeWidth={1.6} className="flex-none text-text-tertiary" aria-hidden="true" />
              ) : (
                <File size={13} strokeWidth={1.6} className="flex-none text-text-tertiary" aria-hidden="true" />
              )}
              <span className="min-w-0 truncate">{node.name}</span>
              {marker && <span className={cn("h-1.5 w-1.5 flex-none rounded-full", MARKER_CLASS[marker])} title={marker} aria-label={marker} />}
              {!folder && <span className="ml-auto flex-none pl-1.5 text-[10.5px] text-text-tertiary">{formatSize(node.size_bytes)}</span>}
            </button>
            {open && node.children && (
              <FileTree
                nodes={node.children}
                expanded={expanded}
                onToggle={onToggle}
                onSelect={onSelect}
                selectedPath={selectedPath}
                markers={markers}
                depth={depth + 1}
              />
            )}
          </li>
        );
      })}
    </ul>
  );
}
