import { describe, expect, it } from "vitest";
import { groupReportHistory, isAiSection, mermaidEdgeCount, splitUngrounded } from "@/lib/reportFormat";
import type { ReportResponse, ReportSection } from "@/lib/types/reports";

const row = (id: string, type: string, status: string) => ({ id, report_type: type, status }) as unknown as ReportResponse;

describe("reportFormat", () => {
  it("identifies the AI section by heading", () => {
    expect(isAiSection({ heading: "Narrative Overview" } as ReportSection, "summary")).toBe(true);
    expect(isAiSection({ heading: "Narrative Overview" } as ReportSection, "health")).toBe(false);
  });

  it("splits the ungrounded prefix", () => {
    const p = "[AI interpretation could not be fully grounded in repository evidence — treat as unverified.] ";
    expect(splitUngrounded(`${p}Body`)).toEqual({ ungrounded: true, text: "Body" });
    expect(splitUngrounded("Body")).toEqual({ ungrounded: false, text: "Body" });
  });

  it("counts mermaid edges", () => {
    expect(mermaidEdgeCount("graph LR\n  a --> b\n  b --> c\n  c")).toBe(2);
  });

  it("groups history newest-first and flags a failed latest attempt", () => {
    const g = groupReportHistory([row("3", "summary", "failed"), row("2", "summary", "ready"), row("1", "summary", "ready"), row("4", "health", "ready")]);
    expect(g.summary.latestFailed?.id).toBe("3");
    expect(g.summary.ready?.id).toBe("2");
    expect(g.summary.history).toHaveLength(3);
    expect(g.health.latestFailed).toBeNull();
  });
});
