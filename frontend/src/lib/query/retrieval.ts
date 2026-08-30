"use client";

import { useQuery } from "@tanstack/react-query";
import { retrievalApi } from "@/lib/api/retrieval";
import { queryKeys } from "@/lib/query/keys";

export function useRetrievalQuery(id: string | undefined, q: string, opts?: { sources?: string[]; enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.retrieval(id ?? "", q, opts?.sources),
    queryFn: () => retrievalApi.query(id as string, q, { sources: opts?.sources }),
    enabled: Boolean(id) && q.trim().length > 0 && (opts?.enabled ?? true),
  });
}
