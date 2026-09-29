/** Centralized TanStack Query key factory — one place, no ad-hoc key arrays scattered across pages. */
export const queryKeys = {
  repositories: () => ["repositories"] as const,
  repository: (id: string) => ["repositories", id] as const,
  workspace: (id: string) => ["repositories", id, "workspace"] as const,
  tree: (id: string) => ["repositories", id, "tree"] as const,
  intelligence: (id: string) => ["repositories", id, "intelligence"] as const,
  callGraph: (id: string) => ["repositories", id, "call-graph"] as const,
  dependencyGraph: (id: string) => ["repositories", id, "dependency-graph"] as const,
  symbols: (id: string) => ["repositories", id, "symbols"] as const,
  knowledgeState: (id: string) => ["repositories", id, "knowledge"] as const,
  chunks: (id: string, params?: Record<string, unknown>) => ["repositories", id, "knowledge", "chunks", params] as const,
  retrieval: (id: string, q: string, sources?: string[], topK?: number, rerank?: boolean) =>
    ["repositories", id, "retrieval", q, sources?.join(",") ?? "", topK ?? null, rerank ?? null] as const,
  reportsList: (id: string, latestOnly: boolean) => ["repositories", id, "reports", { latestOnly }] as const,
  report: (id: string, type: string) => ["repositories", id, "reports", type] as const,
};
