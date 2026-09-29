/** Mirrors backend/app/reports/schemas.py. */

export const REPORT_TYPES = ["summary", "architecture", "dependency_risk", "health", "onboarding"] as const;
export type ReportType = (typeof REPORT_TYPES)[number];

export const REPORT_TYPE_TITLES: Record<ReportType, string> = {
  summary: "Repository Overview",
  architecture: "Architecture Report",
  dependency_risk: "Dependency & Risk Report",
  health: "Codebase Health Report",
  onboarding: "Developer Onboarding Guide",
};

export const EVIDENCE_CONFIDENCE_VALUES = ["verified", "derived", "partial", "insufficient_evidence"] as const;
export type EvidenceConfidence = (typeof EVIDENCE_CONFIDENCE_VALUES)[number];

export interface EvidenceReference {
  source: string;
  file_path?: string | null;
  symbol_name?: string | null;
  start_line?: number | null;
  end_line?: number | null;
  relationship_type?: string | null;
  description?: string | null;
}

export interface ReportSection {
  heading: string;
  content: string;
  confidence: EvidenceConfidence;
  evidence: EvidenceReference[];
  metrics: Record<string, unknown>;
  findings: string[];
}

export interface ReportDiagram {
  title: string;
  diagram_type: string;
  mermaid_code: string;
}

export interface GenerateReportRequest {
  force_regenerate?: boolean;
}

export type ReportStatus = "pending" | "generating" | "ready" | "failed";

export interface ReportResponse {
  id: string;
  repository_id: string;
  report_type: string;
  status: ReportStatus;
  title: string | null;
  summary: string | null;
  sections: ReportSection[];
  diagrams: ReportDiagram[];
  generation_metadata: Record<string, unknown>;
  repository_version: string | null;
  generated_at: string | null;
  created_at: string;
  error_message: string | null;
  stale: boolean;
}

export interface ReportListData {
  repository_id: string;
  latest_only: boolean;
  reports: ReportResponse[];
}
