/** Mirrors backend/app/knowledge/schemas.py. */

export interface KnowledgeIndexStateResponse {
  id: string;
  repository_id: string;
  status: "pending" | "indexing" | "ready" | "failed";
  progress: number;
  error_message: string | null;
  embedding_model_version: string | null;
  total_files_considered: number;
  total_files_skipped_unchanged: number;
  total_files_failed: number;
  total_chunks: number;
  total_chunks_from_cache: number;
  total_chunks_embedded_fresh: number;
  last_indexed_at: string | null;
  chunking_ms: number | null;
  embedding_ms: number | null;
  upsert_ms: number | null;
  total_ms: number | null;
  created_at: string;
  updated_at: string;
}

export interface ChunkResponse {
  id: string;
  file_id: string;
  symbol_id: string | null;
  chunk_index: number;
  chunk_type: string;
  start_line: number;
  end_line: number;
  char_count: number;
  language: string | null;
  content_hash: string;
  embedding_model_version: string;
}

export interface ChunkListData {
  repository_id: string;
  chunks: ChunkResponse[];
  limit: number;
  offset: number;
}

export interface KnowledgeReindexResponse {
  repository_id: string;
  message: string;
}
