"use client";

import { Fragment, useMemo } from "react";
import { parseAnswer, type Inline } from "@/lib/answerFormat";
import type { Citation } from "@/lib/types/ai";
import { cn } from "@/lib/utils";

/**
 * Renders an Ask answer with every cited file path / `symbol()` that
 * matches retrieved evidence as a button that opens that evidence.
 * Hover state is shared with the evidence rail so a claim and its source
 * light up together (the Evidence Trail made interactive).
 */
export function AnswerProse({
  text,
  evidence,
  hovered,
  onHover,
  onCite,
  muted,
}: {
  text: string;
  evidence: Citation[];
  hovered?: number | null;
  onHover?: (i: number | null) => void;
  onCite?: (i: number) => void;
  muted?: boolean;
}) {
  const blocks = useMemo(() => parseAnswer(text, evidence), [text, evidence]);
  const renderInline = (nodes: Inline[]) =>
    nodes.map((n, i) => {
      if (n.kind === "text") return <Fragment key={i}>{n.text}</Fragment>;
      if (n.kind === "strong") return <strong key={i}>{renderInline(n.children)}</strong>;
      if (n.kind === "lines") return <span key={i} className="cs-lines">{n.text}</span>;
      const cls = cn("cs-art", n.variant === "path" && "cs-art-path", n.variant === "sym" && "cs-art-sym");
      if (n.cite === null) return <span key={i} className={cls}>{n.text}</span>;
      const cite = n.cite;
      const ev = evidence[cite];
      return (
        <button
          key={i}
          type="button"
          className={cls}
          data-hl={hovered === cite}
          onMouseEnter={() => onHover?.(cite)}
          onMouseLeave={() => onHover?.(null)}
          onFocus={() => onHover?.(cite)}
          onBlur={() => onHover?.(null)}
          onClick={() => onCite?.(cite)}
          aria-label={`${n.text} — inspect evidence ${cite + 1}: ${ev.file_path}${ev.start_line ? ` lines ${ev.start_line}–${ev.end_line}` : ""}`}
        >
          {n.text}
        </button>
      );
    });

  return (
    <div className={cn("cs-prose", muted && "cs-prose-muted")}>
      {blocks.map((b, i) =>
        b.kind === "p" ? (
          <p key={i}>{renderInline(b.inlines)}</p>
        ) : b.kind === "ul" ? (
          <ul key={i}>{b.items.map((it, j) => <li key={j}>{renderInline(it)}</li>)}</ul>
        ) : (
          <ol key={i}>{b.items.map((it, j) => <li key={j}>{renderInline(it)}</li>)}</ol>
        ),
      )}
    </div>
  );
}
