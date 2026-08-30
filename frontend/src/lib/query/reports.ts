"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { reportsApi } from "@/lib/api/reports";
import { queryKeys } from "@/lib/query/keys";
import type { ReportType } from "@/lib/types/reports";

export function useReportsList(id: string | undefined, latestOnly = true) {
  return useQuery({
    queryKey: queryKeys.reportsList(id ?? "", latestOnly),
    queryFn: () => reportsApi.list(id as string, latestOnly),
    enabled: Boolean(id),
  });
}

export function useReport(id: string | undefined, type: ReportType | undefined) {
  return useQuery({
    queryKey: queryKeys.report(id ?? "", type ?? ""),
    queryFn: () => reportsApi.get(id as string, type as ReportType),
    enabled: Boolean(id) && Boolean(type),
    retry: false,
  });
}

export function useGenerateReport() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, type, force }: { id: string; type: ReportType; force?: boolean }) =>
      reportsApi.generate(id, type, force),
    onSuccess: (_data, vars) => {
      client.invalidateQueries({ queryKey: queryKeys.report(vars.id, vars.type) });
      client.invalidateQueries({ queryKey: queryKeys.reportsList(vars.id, true) });
    },
  });
}
