import { api } from "@/lib/api/client";
import type { ReportListData, ReportResponse, ReportType } from "@/lib/types/reports";

/** Mirrors backend/app/reports/api.py. */
export const reportsApi = {
  list: (repositoryId: string, latestOnly = true) =>
    api.get<ReportListData>(`/repositories/${repositoryId}/reports`, { query: { latest_only: latestOnly } }),
  get: (repositoryId: string, reportType: ReportType) =>
    api.get<ReportResponse>(`/repositories/${repositoryId}/reports/${reportType}`),
  generate: (repositoryId: string, reportType: ReportType, forceRegenerate = false) =>
    api.post<ReportResponse>(`/repositories/${repositoryId}/reports/${reportType}`, {
      force_regenerate: forceRegenerate,
    }, { timeoutMs: 60_000 }),
};
