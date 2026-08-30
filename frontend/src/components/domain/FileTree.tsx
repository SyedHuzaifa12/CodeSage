"use client";

import { useState } from "react";
import { ChevronRight, File, Folder } from "lucide-react";
import type { TreeNode } from "@/lib/types/workspace";
import { cn } from "@/lib/utils";

/**
 * Desktop file tree (Explorer). Recursive, collapsible. Sprint 7 note
 * (Design System §10): true windowed virtualization is a documented
 * follow-up for repositories with thousands of files — out of scope for
 * this sprint's validation fixtures (flask-blog/microblog, both well
 * under that threshold) but flagged in the implementation spec.
 */
interface FileTreeProps {
  nodes: TreeNode[];
  depth?: number;
  onSelect?: (n: TreeNode) => void;
  selectedPath?: string | null;
}

export function FileTree({ nodes, depth = 0, onSelect, selectedPath = null }: FileTreeProps) {
  return (
    <ul role={depth === 0 ? "tree" : "group"} className="flex flex-col">
      {nodes.map((node) => (
        <TreeRow key={node.path} node={node} depth={depth} onSelect={onSelect} selectedPath={selectedPath} />
      ))}
    </ul>
  );
}

function TreeRow({ node, depth, onSelect, selectedPath }: { node: TreeNode; depth: number; onSelect?: (n: TreeNode) => void; selectedPath: string | null }) {
  const [open, setOpen] = useState(depth === 0);
  const isDir = node.type === "directory" && node.children;

  return (
    <li role="treeitem" aria-expanded={isDir ? open : undefined} aria-selected={node.path === selectedPath}>
      <button
        onClick={() => (isDir ? setOpen((v) => !v) : onSelect?.(node))}
        className="flex w-full items-center gap-1.5 rounded-sm py-1 text-left font-mono text-[12px] text-text-secondary hover:text-text-primary focus-visible:outline-2"
        style={{ paddingLeft: depth * 16 }}
      >
        {isDir ? (
          <ChevronRight size={12} className={cn("flex-shrink-0 transition-transform", open && "rotate-90")} aria-hidden="true" />
        ) : (
          <span className="w-3 flex-shrink-0" />
        )}
        {isDir ? (
          <Folder size={13} strokeWidth={1.6} className="flex-shrink-0 text-text-tertiary" aria-hidden="true" />
        ) : (
          <File size={13} strokeWidth={1.6} className="flex-shrink-0 text-text-tertiary" aria-hidden="true" />
        )}
        <span className="truncate">{node.name}</span>
      </button>
      {isDir && open && node.children && (
        <FileTree nodes={node.children} depth={depth + 1} onSelect={onSelect} selectedPath={selectedPath} />
      )}
    </li>
  );
}
