import { api } from "@/lib/api/client";
import type {
  CallGraphData,
  DependencyGraphData,
  IndexTriggerResponse,
  IntelligenceResponse,
  RepositoryTreeData,
  SymbolExplorerData,
  WorkspaceResponse,
} from "@/lib/types/workspace";

/** Mirrors backend/app/ingestion/api.py — nested under /repositories/{id}/... */
export const workspaceApi = {
  get: (repositoryId: string) => api.get<WorkspaceResponse>(`/repositories/${repositoryId}/workspace`),
  tree: (repositoryId: string) => api.get<RepositoryTreeData>(`/repositories/${repositoryId}/tree`),
  refresh: (repositoryId: string) => api.post<WorkspaceResponse>(`/repositories/${repositoryId}/refresh`),
  reset: (repositoryId: string) => api.post<WorkspaceResponse>(`/repositories/${repositoryId}/reset`),
  triggerIndex: (repositoryId: string) =>
    api.post<IndexTriggerResponse>(`/repositories/${repositoryId}/index`),
  intelligence: (repositoryId: string) =>
    api.get<IntelligenceResponse>(`/repositories/${repositoryId}/intelligence`),
  callGraph: (repositoryId: string) => api.get<CallGraphData>(`/repositories/${repositoryId}/call-graph`),
  dependencyGraph: (repositoryId: string) =>
    api.get<DependencyGraphData>(`/repositories/${repositoryId}/dependency-graph`),
  symbols: (repositoryId: string) => api.get<SymbolExplorerData>(`/repositories/${repositoryId}/symbols`),
};
