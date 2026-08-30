"use client";

import { useState } from "react";
import Link from "next/link";
import { useRepositoryContext } from "@/context/RepositoryContext";
import { FileTree } from "@/components/domain/FileTree";
import { SkeletonBlock } from "@/components/state/Loading";
import { EmptyState, ErrorPanel } from "@/components/state/StateVocabulary";
import { useSymbols, useTree } from "@/lib/query/workspace";
import { ApiError } from "@/lib/api/client";
import type { TreeNode } from "@/lib/types/workspace";

export default function ExplorerPage() {
  const { repositoryId, isReady } = useRepositoryContext();
  const tree = useTree(repositoryId);
  const symbols = useSymbols(repositoryId, { enabled: isReady });
  const [selected, setSelected] = useState<TreeNode | null>(null);

  const fileSymbols = selected ? symbols.data?.symbols.filter((s) => s.file_path === selected.path) ?? [] : [];

  return (
    <div className="flex h-[calc(100vh-56px)] gap-10 px-11 py-6">
      <div className="w-[320px] flex-shrink-0 overflow-y-auto cs-scrollbar">
        <div className="cs-mono-label mb-3">FILE TREE</div>
        {tree.isLoading && <SkeletonBlock />}
        {tree.isError && <ErrorPanel message={tree.error instanceof ApiError ? tree.error.message : "Couldn't load the file tree."} />}
        {tree.data && tree.data.root.length === 0 && <EmptyState message="No files scanned yet." />}
        {tree.data && tree.data.root.length > 0 && (
          <FileTree nodes={tree.data.root} onSelect={setSelected} selectedPath={selected?.path ?? null} />
        )}
      </div>

      <div className="min-w-0 flex-1 overflow-y-auto cs-scrollbar border-l border-border-subtle pl-10">
        {!selected && <EmptyState message="Select a file to see its parsed symbols." />}
        {selected && (
          <>
            <div className="font-display text-[22px] italic text-text-primary">{selected.name}</div>
            <div className="mt-1 font-mono text-[10.5px] text-text-tertiary">{selected.path}</div>

            {!isReady && (
              <p className="mt-6 text-small text-text-secondary">
                Symbol intelligence unlocks once indexing finishes — the raw file path is shown above in the meantime.
              </p>
            )}

            {isReady && (
              <div className="mt-6 flex flex-col gap-1">
                {fileSymbols.length === 0 && <EmptyState message="No parsed symbols for this file." />}
                {fileSymbols.map((sym) => (
                  <div key={sym.id} className="flex items-baseline justify-between border-b border-border-subtle py-2">
                    <div>
                      <span className="font-mono text-[12px] text-[oklch(0.85_0.1_300)]">{sym.name}</span>
                      <span className="ml-2 font-mono text-[10px] text-text-tertiary">{sym.symbol_type}</span>
                    </div>
                    <span className="font-mono text-[10.5px] text-text-tertiary">
                      {sym.start_line}–{sym.end_line}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {isReady && (
              <Link
                href={`/r/${repositoryId}/ask?q=${encodeURIComponent(`Explain ${selected.path}`)}`}
                className="mt-6 inline-block font-mono text-[10.5px] text-violet hover:underline"
              >
                ask about this file &rarr;
              </Link>
            )}
          </>
        )}
      </div>
    </div>
  );
}
