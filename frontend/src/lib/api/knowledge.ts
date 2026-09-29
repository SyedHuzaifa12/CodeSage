import { api } from "@/lib/api/client";
import type { ChunkListData, KnowledgeIndexStateResponse, KnowledgeReindexResponse } from "@/lib/types/knowledge";

/** Mirrors backend/app/knowledge/api.py — nested under /repositories/{id}/knowledge/... */
export const knowledgeApi = {
  getState: (repositoryId: string) =>
    api.get<KnowledgeIndexStateResponse>(`/repositories/${repositoryId}/knowledge`),
  listChunks: (repositoryId: string, params?: { fileId?: string; chunkType?: string; limit?: number; offset?: number }) =>
    api.get<ChunkListData>(`/repositories/${repositoryId}/knowledge/chunks`, {
      query: {
        file_id: params?.fileId,
        chunk_type: params?.chunkType,
        limit: params?.limit,
        offset: params?.offset,
      },
    }),
  reindex: (repositoryId: string) =>
    api.post<KnowledgeReindexResponse>(`/repositories/${repositoryId}/knowledge/reindex`),
};
