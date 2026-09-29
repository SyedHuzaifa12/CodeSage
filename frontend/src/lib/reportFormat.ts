import type { ReportResponse, ReportSection, ReportType } from "@/lib/types/reports";

/**
 * The single AI-written section each synthesized report type appends
 * (backend/app/reports/generators/*.py `ai_section_headings`). Every other
 * section is deterministic — read or computed straight from the index.
 */
export const AI_SECTION_HEADINGS: Record<ReportType, string | null> = {
  summary: "Narrative Overview",
  architecture: "Architecture Narrative",
  dependency_risk: null,
  health: null,
  onboarding: "Getting Started Narrative",
};

export const REPORT_DESCRIPTIONS: Record<ReportType, string> = {
  summary: "Size, languages, structure, entry points, dependency hotspots and architectural signals, with a short AI-written narrative.",
  architecture: "Major modules, dependency direction and tightly coupled areas, plus two diagrams drawn from resolved relationships.",
  dependency_risk: "Hotspots with a risk level, circular dependencies, orphan files and the most-called symbols. Fully deterministic.",
  health: "Size, largest modules, dependency concentration, complexity signals, tests and documentation. Fully deterministic.",
  onboarding: "Where to start, important modules, files likely to change, persistence and tests, with a getting-started narrative.",
};

const UNGROUNDED_PREFIX =
  "[AI interpretation could not be fully grounded in repository evidence — treat as unverified.] ";

export function isAiSection(section: ReportSection, type: ReportType): boolean {
  return AI_SECTION_HEADINGS[type] === section.heading;
}

/** Separates the backend's "could not be grounded" prefix so it can be shown as a notice, not prose. */
export function splitUngrounded(content: string): { ungrounded: boolean; text: string } {
  if (content.startsWith(UNGROUNDED_PREFIX)) return { ungrounded: true, text: content.slice(UNGROUNDED_PREFIX.length) };
  return { ungrounded: false, text: content };
}

/** Relationship count behind a deterministic Mermaid diagram — every `-->` line is one resolved edge. */
export function mermaidEdgeCount(code: string): number {
  return code.split("\n").filter((l) => l.includes("-->")).length;
}

export interface ReportTypeStatus {
  /** Latest ready row, if any. */
  ready: ReportResponse | null;
  /** True when the newest attempt failed (the previous ready row, if any, is still what GET returns). */
  latestFailed: ReportResponse | null;
  history: ReportResponse[];
}

/** Groups `GET /reports?latest_only=false` (newest first) by type. */
export function groupReportHistory(rows: ReportResponse[]): Record<string, ReportTypeStatus> {
  const out: Record<string, ReportTypeStatus> = {};
  for (const row of rows) {
    const bucket = (out[row.report_type] ??= { ready: null, latestFailed: null, history: [] });
    if (bucket.history.length === 0 && row.status === "failed") bucket.latestFailed = row;
    if (!bucket.ready && row.status === "ready") bucket.ready = row;
    bucket.history.push(row);
  }
  return out;
}
