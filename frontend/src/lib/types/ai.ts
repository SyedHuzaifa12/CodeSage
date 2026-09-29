/** Mirrors backend/app/ai/schemas/{dto,verification,intent}.py. */

export const VERIFICATION_STATUSES = [
  "supported",
  "partially_supported",
  "insufficient_evidence",
  "contradicted",
] as const;
export type VerificationStatus = (typeof VERIFICATION_STATUSES)[number];

export const QUERY_INTENTS = [
  "architecture_overview",
  "implementation",
  "symbol_lookup",
  "dependency_analysis",
  "call_relationships",
  "impact_analysis",
  "debugging",
  "configuration",
  "database_data_flow",
  "testing",
  "security",
  "general",
] as const;
export type QueryIntent = (typeof QUERY_INTENTS)[number];

export interface AskOptions {
  top_k?: number;
  sources?: string[];
  force_refresh?: boolean;
}

export interface AskRequest {
  query: string;
  options?: AskOptions;
}

export interface Citation {
  file_path: string;
  symbol_name: string | null;
  symbol_type: string | null;
  start_line: number | null;
  end_line: number | null;
  retrieval_score: number;
  retrieval_sources: string[];
}

export interface VerificationInfo {
  status: VerificationStatus;
  reasons: string[];
}

/**
 * The AI Engine's real LangGraph pipeline stages (ai/engine/orchestrator.py):
 * intent -> retrieval -> evidence_selection -> context_construction -> llm
 * -> verification -> formatting. The Reasoning Ribbon UI collapses these into
 * four reader-facing stages — see lib/reasoningRibbon.ts for the exact,
 * documented mapping decision.
 */
export interface StageLatency {
  intent_ms: number;
  retrieval_ms: number;
  evidence_selection_ms: number;
  context_construction_ms: number;
  llm_ms: number;
  verification_ms: number;
  formatting_ms: number;
  total_ms: number;
}

export interface AskMetadata {
  intent: QueryIntent | string;
  provider: string;
  model: string;
  cache_hit: boolean;
  retry_count: number;
  stage_latency_ms: StageLatency;
  retrieval_candidates: number;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
}

export interface AskResponseData {
  repository_id: string;
  query: string;
  answer: string;
  explanation?: string | null;
  evidence: Citation[];
  relevant_files: string[];
  relevant_symbols: string[];
  verification: VerificationInfo;
  metadata: AskMetadata;
}
