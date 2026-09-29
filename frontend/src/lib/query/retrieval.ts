"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { retrievalApi } from "@/lib/api/retrieval";
import { queryKeys } from "@/lib/query/keys";

export interface RetrievalOptions {
  sources?: string[];
  topK?: number;
  rerank?: boolean;
  enabled?: boolean;
}

export function useRetrievalQuery(id: string | undefined, q: string, opts: RetrievalOptions = {}) {
  return useQuery({
    queryKey: queryKeys.retrieval(id ?? "", q, opts.sources, opts.topK, opts.rerank),
    queryFn: () => retrievalApi.query(id as string, q, { sources: opts.sources, topK: opts.topK, rerank: opts.rerank }),
    enabled: Boolean(id) && q.trim().length > 0 && (opts.enabled ?? true),
    placeholderData: keepPreviousData,
    retry: false,
  });
}
