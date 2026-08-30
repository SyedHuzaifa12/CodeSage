"use client";

import type { EvidenceResult } from "@/lib/types/retrieval";
import { cn } from "@/lib/utils";

const SOURCE_COLOR: Record<string, string> = {
  semantic: "oklch(0.85 0.1 300)",
  lexical: "oklch(0.72 0.09 200)",
  structural: "oklch(0.78 0.12 70)",
};

/** Search result row (Design System §16 Search): hairline-separated, path+snippet left, badges+score right. */
export function SearchResultRow({ result, onAsk }: { result: EvidenceResult; onAsk?: () => void }) {
  const primarySource = result.sources[0];
  const location =
    result.start_line && result.end_line ? `${result.file_path}:${result.start_line}–${result.end_line}` : result.file_path;

  return (
    <div className="flex items-baseline justify-between gap-6 border-t border-border-subtle py-[18px]">
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div
          className="truncate font-mono text-[12.5px]"
          style={{ color: primarySource ? SOURCE_COLOR[primarySource] : "var(--cs-text-primary)" }}
        >
          {location}
        </div>
        {result.qualified_name && (
          <div className="truncate font-mono text-[12px] text-text-secondary">{result.qualified_name}</div>
        )}
        {onAsk && (
          <button onClick={onAsk} className="w-fit font-mono text-[10px] text-violet hover:underline">
            ask about this &rarr;
          </button>
        )}
      </div>
      <div className="flex flex-shrink-0 flex-col items-end gap-1.5">
        <span className="font-mono text-[9px] text-text-tertiary">{result.sources.join(" · ")}</span>
        <span
          className={cn("font-mono text-[14px]")}
          style={{ color: primarySource ? SOURCE_COLOR[primarySource] : "var(--cs-text-primary)" }}
        >
          {result.final_score.toFixed(2)}
        </span>
      </div>
    </div>
  );
}
