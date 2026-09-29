"use client";

import { cn } from "@/lib/utils";

/**
 * Signature device #1 — Topology Mark (Design System §17-A).
 *
 * A small, asymmetric five-node constellation glyph. Ported VERBATIM from
 * the approved design canvas (`.claude/design/Main.dc.html` /
 * `Components.dc.html`): viewBox 0 0 26 20, paths
 * M4,15 L11,5 / M11,5 L19,9 / M19,9 L23,17 / M11,5 L14,17 / M4,15 L14,17,
 * circles at (4,15) r1.7, (11,5) r2.1, (19,9) r1.7, (23,17) r1.5, (14,17) r1.5.
 * This is the ONE place this markup is defined — every other component
 * reuses it, never redraws it.
 *
 * Variants:
 * - "mark": the compact logomark (nav/header/identity).
 * - "watermark": the same glyph, scattered and scaled up at ~5% opacity,
 *   forming an atmospheric knowledge-graph texture behind hero zones
 *   (Overview, Onboarding). Never sits under body text at reading contrast.
 * - "assembling": the onboarding foreground device — a larger constellation
 *   (ported from `Onboarding.dc.html`) that visibly assembles node-by-node
 *   as `progress` (0-1) increases, literally visualizing "being understood."
 */

export type TopologyMarkVariant = "mark" | "watermark" | "assembling";

interface TopologyMarkProps {
  variant?: TopologyMarkVariant;
  /** Used by "mark": pixel width; height follows the 26:20 aspect ratio. */
  size?: number;
  /** Used by "assembling": 0-1 fraction of the knowledge map constructed. */
  progress?: number;
  className?: string;
  /** Accessible label — the mark is decorative by default (aria-hidden) unless this is set. */
  title?: string;
}

const MARK_STROKE = "oklch(0.78 0.13 300 / 0.65)";
const MARK_FILL = "oklch(0.85 0.13 300)";

function MarkGlyph({ size = 24 }: { size?: number }) {
  const height = Math.round((size * 20) / 26);
  return (
    <svg width={size} height={height} viewBox="0 0 26 20" aria-hidden="true">
      <g stroke={MARK_STROKE} strokeWidth={1}>
        <path d="M4,15 L11,5" />
        <path d="M11,5 L19,9" />
        <path d="M19,9 L23,17" />
        <path d="M11,5 L14,17" />
        <path d="M4,15 L14,17" />
      </g>
      <g fill={MARK_FILL}>
        <circle cx={4} cy={15} r={1.7} />
        <circle cx={11} cy={5} r={2.1} />
        <circle cx={19} cy={9} r={1.7} />
        <circle cx={23} cy={17} r={1.5} />
        <circle cx={14} cy={17} r={1.5} />
      </g>
    </svg>
  );
}

/** Deterministic scatter seed (never randomized per-render — avoids hydration mismatch). */
const WATERMARK_INSTANCES = [
  { x: 980, y: 60, scale: 5.5, rotate: 8 },
  { x: 90, y: 640, scale: 4.2, rotate: -14 },
  { x: 1220, y: 520, scale: 3.4, rotate: 22 },
  { x: 520, y: 40, scale: 2.6, rotate: -6 },
];

function TopologyWatermark({ className }: { className?: string }) {
  return (
    <svg
      className={cn("pointer-events-none absolute inset-0 h-full w-full", className)}
      viewBox="0 0 1440 900"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
      style={{ opacity: "var(--cs-watermark-opacity)" }}
    >
      {WATERMARK_INSTANCES.map((inst, i) => (
        <g key={i} transform={`translate(${inst.x} ${inst.y}) scale(${inst.scale}) rotate(${inst.rotate})`}>
          <g stroke="oklch(0.75 0.13 300)" strokeWidth={1} fill="none">
            <path d="M4,15 L11,5" />
            <path d="M11,5 L19,9" />
            <path d="M19,9 L23,17" />
            <path d="M11,5 L14,17" />
            <path d="M4,15 L14,17" />
          </g>
          <g fill="oklch(0.8 0.13 300)">
            <circle cx={4} cy={15} r={1.7} />
            <circle cx={11} cy={5} r={2.1} />
            <circle cx={19} cy={9} r={1.7} />
            <circle cx={23} cy={17} r={1.5} />
            <circle cx={14} cy={17} r={1.5} />
          </g>
        </g>
      ))}
    </svg>
  );
}

/** Ported from Onboarding.dc.html's "topology assembling itself" panel. */
const ASSEMBLING_NODES = [
  { id: "root", x: 190, y: 190, r: 10, order: 0 },
  { id: "a", x: 260, y: 130, r: 7, order: 1 },
  { id: "b", x: 120, y: 140, r: 7, order: 1 },
  { id: "c", x: 240, y: 260, r: 6, order: 2 },
  { id: "d", x: 130, y: 260, r: 4, order: 3 },
  { id: "e", x: 310, y: 90, r: 4, order: 3 },
  { id: "f", x: 70, y: 110, r: 4, order: 3 },
];
const ASSEMBLING_SOLID_EDGES = [
  ["root", "a"],
  ["root", "b"],
  ["root", "c"],
];
const ASSEMBLING_DASHED_EDGES = [
  ["root", "d"],
  ["a", "e"],
  ["b", "f"],
];

function nodeById(id: string) {
  return ASSEMBLING_NODES.find((n) => n.id === id)!;
}

function TopologyAssembling({ progress = 0.5, className }: { progress?: number; className?: string }) {
  const maxOrder = Math.max(...ASSEMBLING_NODES.map((n) => n.order));
  const revealOrder = progress * maxOrder;

  return (
    <svg width={380} height={380} viewBox="0 0 380 380" className={className} aria-hidden="true">
      <circle cx={190} cy={190} r={170} fill="none" stroke="oklch(1 0 0 / 0.04)" />
      <circle cx={190} cy={190} r={120} fill="none" stroke="oklch(1 0 0 / 0.05)" />

      <g strokeWidth={1}>
        {ASSEMBLING_SOLID_EDGES.map(([from, to], i) => {
          const a = nodeById(from);
          const b = nodeById(to);
          const revealed = Math.max(a.order, b.order) <= revealOrder;
          return (
            <line
              key={`solid-${i}`}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              stroke={revealed ? "oklch(0.75 0.13 300 / 0.4)" : "oklch(1 0 0 / 0.06)"}
            />
          );
        })}
        {ASSEMBLING_DASHED_EDGES.map(([from, to], i) => {
          const a = nodeById(from);
          const b = nodeById(to);
          const revealed = Math.max(a.order, b.order) <= revealOrder;
          return (
            <line
              key={`dashed-${i}`}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              stroke={revealed ? "oklch(0.65 0.1 300 / 0.35)" : "oklch(1 0 0 / 0.08)"}
              strokeDasharray="2 4"
            />
          );
        })}
      </g>

      {ASSEMBLING_NODES.map((n) => {
        const revealed = n.order <= revealOrder;
        return (
          <circle
            key={n.id}
            cx={n.x}
            cy={n.y}
            r={n.r}
            fill={revealed ? (n.order === 0 ? MARK_FILL : "oklch(0.8 0.13 300)") : "oklch(0.4 0.02 280)"}
            opacity={revealed ? 1 : 0.4}
          />
        );
      })}
    </svg>
  );
}

export function TopologyMark({ variant = "mark", size = 24, progress, className, title }: TopologyMarkProps) {
  const content = (() => {
    switch (variant) {
      case "watermark":
        return <TopologyWatermark className={className} />;
      case "assembling":
        return <TopologyAssembling progress={progress} className={className} />;
      case "mark":
      default:
        return (
          <span className={className}>
            <MarkGlyph size={size} />
          </span>
        );
    }
  })();

  if (title) {
    return (
      <span role="img" aria-label={title}>
        {content}
      </span>
    );
  }
  return content;
}
