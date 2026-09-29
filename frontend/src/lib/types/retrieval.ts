/** Mirrors backend/app/retrieval/schemas.py. */

export type RetrievalSource = "semantic" | "lexical" | "structural";

export interface SourceScore {
  source: string;
  score: number;
}

export interface EvidenceResult {
  rank: number;
  final_score: number;
  rerank_score: number | null;
  repository_id: string;
  file_id: string;
  file_path: string;
  chunk_id: string | null;
  symbol_id: string | null;
  symbol_name: string | null;
  qualified_name: string | null;
  symbol_type: string | null;
  start_line: number | null;
  end_line: number | null;
  language: string | null;
  sources: string[];
  source_scores: SourceScore[];
  reasons: string[];
}

export interface RetrievalStats {
  candidates_semantic: number;
  candidates_lexical: number;
  candidates_structural: number;
  candidates_after_dedup: number;
  stage_latency_ms: Record<string, number>;
  total_latency_ms: number;
  cache_hit: boolean;
  sources_failed: string[];
  reranking_applied: boolean;
}

export interface RetrievalQueryData {
  repository_id: string;
  query: string;
  top_k: number;
  sources_requested: string[];
  results: EvidenceResult[];
  stats: RetrievalStats;
}
