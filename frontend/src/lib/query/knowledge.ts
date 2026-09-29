"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { knowledgeApi } from "@/lib/api/knowledge";
import { queryKeys } from "@/lib/query/keys";

export function useKnowledgeState(id: string | undefined, opts?: { poll?: boolean }) {
  return useQuery({
    queryKey: queryKeys.knowledgeState(id ?? ""),
    queryFn: () => knowledgeApi.getState(id as string),
    enabled: Boolean(id),
    refetchInterval: opts?.poll ? 2_000 : false,
    retry: 1,
  });
}

export function useChunks(id: string | undefined, params?: { fileId?: string; chunkType?: string; limit?: number; offset?: number }) {
  return useQuery({
    queryKey: queryKeys.chunks(id ?? "", params),
    queryFn: () => knowledgeApi.listChunks(id as string, params),
    enabled: Boolean(id),
  });
}

export function useReindex() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => knowledgeApi.reindex(id),
    onSuccess: (_data, id) => client.invalidateQueries({ queryKey: queryKeys.knowledgeState(id) }),
  });
}
