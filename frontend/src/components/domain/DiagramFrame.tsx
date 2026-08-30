"use client";

import { useEffect, useRef, useState } from "react";
import { SkeletonBlock } from "@/components/state/Loading";
import { ErrorPanel } from "@/components/state/StateVocabulary";

let mermaidInitialized = false;

/**
 * Diagram Frame (Design System §9.4/§10): renders a report's Mermaid
 * diagram, lazy (only when scrolled into view — Mermaid parse+layout is
 * not free), with the "derived from N relationships" footnote reminding
 * the reader diagrams are structurally generated, not AI-invented,
 * matching the backend's own guarantee (Sprint 6).
 */
export function DiagramFrame({
  title,
  mermaidCode,
  footnote,
}: {
  title: string;
  mermaidCode: string;
  footnote?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const node = containerRef.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "200px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        if (!mermaidInitialized) {
          mermaid.initialize({
            startOnLoad: false,
            theme: "dark",
            themeVariables: {
              background: "#232733",
              primaryColor: "#3a2f4d",
              primaryTextColor: "#ece9f2",
              primaryBorderColor: "oklch(0.75 0.13 300)",
              lineColor: "oklch(0.55 0.02 280)",
              fontFamily: "IBM Plex Mono, monospace",
              fontSize: "12px",
            },
          });
          mermaidInitialized = true;
        }
        const id = `mermaid-${Math.random().toString(36).slice(2)}`;
        const { svg: rendered } = await mermaid.render(id, mermaidCode);
        if (!cancelled) setSvg(rendered);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Diagram failed to render.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [visible, mermaidCode]);

  return (
    <div ref={containerRef} className="flex flex-col gap-2">
      <div className="cs-mono-label">{title}</div>
      {error ? (
        <ErrorPanel message={`Couldn't render diagram: ${error}`} />
      ) : svg ? (
        // eslint-disable-next-line react/no-danger -- Mermaid's own sanitized SVG output.
        <div className="cs-scrollbar overflow-x-auto" dangerouslySetInnerHTML={{ __html: svg }} />
      ) : (
        <SkeletonBlock />
      )}
      {footnote && <div className="font-mono text-[9.5px] text-text-tertiary">{footnote}</div>}
    </div>
  );
}
