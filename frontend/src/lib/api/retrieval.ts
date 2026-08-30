import { api } from "@/lib/api/client";
import type { RetrievalQueryData } from "@/lib/types/retrieval";

/** Mirrors backend/app/retrieval/api.py. */
export const retrievalApi = {
  query: (
    repositoryId: string,
    q: string,
    opts?: { topK?: number; sources?: string[]; rerank?: boolean },
  ) =>
    api.get<RetrievalQueryData>(`/repositories/${repositoryId}/retrieval/query`, {
      query: {
        q,
        top_k: opts?.topK,
        sources: opts?.sources?.join(","),
        rerank: opts?.rerank,
      },
    }),
};
