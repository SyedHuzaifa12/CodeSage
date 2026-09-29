"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { ErrorPanel } from "@/components/state/StateVocabulary";
import { mermaidEdgeCount } from "@/lib/reportFormat";

let mermaidInitialized = false;

/**
 * Diagram Frame (Design System §5/§9.4): renders the backend's
 * deterministic Mermaid code with the real `mermaid` library, lazily when
 * scrolled into view. The footnote counts the relationships in the code
 * itself — Sprint 7 read a `relationship_count` field the backend never
 * sends and printed a literal "N".
 */
export function DiagramFrame({ title, mermaidCode, diagramType }: { title: string; mermaidCode: string; diagramType?: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [visible, setVisible] = useState(false);
  const [showSource, setShowSource] = useState(false);
  const edges = mermaidEdgeCount(mermaidCode);

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
            theme: "base",
            securityLevel: "strict",
            fontFamily: "IBM Plex Mono, monospace",
            flowchart: { curve: "basis", nodeSpacing: 36, rankSpacing: 56, htmlLabels: false },
            themeVariables: {
              darkMode: true,
              background: "transparent",
              fontFamily: "IBM Plex Mono, monospace",
              fontSize: "12px",
              primaryColor: "#2a2833",
              primaryTextColor: "#ece9f2",
              primaryBorderColor: "#4a4658",
              secondaryColor: "#2a2833",
              tertiaryColor: "#23212b",
              lineColor: "#8d8799",
              edgeLabelBackground: "#1c1b22",
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
    <figure ref={containerRef} className="cs-panel m-0 mt-[22px] bg-[radial-gradient(oklch(1_0_0/0.055)_1px,transparent_1.2px),linear-gradient(180deg,oklch(0.185_0.009_280),var(--cs-surface-1))] bg-[length:20px_20px,auto] px-[18px] pb-3.5 pt-[18px]">
      <p className="cs-mono-label">
        {title}
        {diagramType && <span className="ml-1 normal-case tracking-normal"> · {diagramType}</span>}
      </p>
      <div className="mt-3">
        {error ? (
          <ErrorPanel title="Couldn't render this diagram" message={error} />
        ) : svg ? (
          // eslint-disable-next-line react/no-danger -- Mermaid's own sanitized SVG output (securityLevel: strict).
          <div className="cs-mermaid cs-scrollbar flex justify-center overflow-x-auto" role="img" aria-label={`${title}: ${edges} dependency relationships`} dangerouslySetInnerHTML={{ __html: svg }} />
        ) : (
          <div className="cs-skel h-[240px]" />
        )}
      </div>
      <figcaption className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <span className="cs-monoline !text-[11px]">derived from {edges} relationships · drawn from repository data, never by AI</span>
        <button onClick={() => setShowSource((v) => !v)} aria-expanded={showSource} className="cs-disclosure-btn">
          mermaid source <ChevronDown size={12} aria-hidden="true" />
        </button>
      </figcaption>
      {showSource && (
        <pre className="cs-scrollbar mt-2 overflow-x-auto rounded-[8px] bg-bg/60 px-4 py-3 font-mono text-[11.5px] leading-relaxed text-text-secondary">{mermaidCode}</pre>
      )}
    </figure>
  );
}
