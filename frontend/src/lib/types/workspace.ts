/** Mirrors backend/app/ingestion/schemas.py. */

export interface WorkspaceResponse {
  id: string;
  repository_id: string;
  status: "pending" | "scanning" | "ready" | "failed";
  progress: number;
  error_message: string | null;
  total_files: number;
  supported_files: number;
  ignored_files: number;
  folder_count: number;
  repository_size_bytes: number;
  language_distribution: Record<string, number>;
  created_at: string;
  updated_at: string;
}

export interface TreeNode {
  name: string;
  type: "file" | "directory" | string;
  path: string;
  children?: TreeNode[] | null;
  language?: string | null;
  size_bytes?: number | null;
}

export interface RepositoryTreeData {
  repository_id: string;
  root: TreeNode[];
}

export interface IndexTriggerResponse {
  repository_id: string;
  workspace_status: string;
  message: string;
}

export interface LargestModule {
  path: string;
  symbol_count: number;
}

export interface DependencyHotspot {
  module_path: string;
  incoming_dependencies: number;
}

export interface IntelligenceResponse {
  id: string;
  repository_id: string;
  status: string;
  progress: number;
  error_message: string | null;
  total_symbols: number;
  total_classes: number;
  total_interfaces: number;
  total_enums: number;
  total_functions: number;
  total_methods: number;
  total_variables: number;
  total_namespaces: number;
  total_imports: number;
  total_calls: number;
  inheritance_count: number;
  dependency_count: number;
  circular_dependencies: string[][];
  orphan_files: string[];
  languages: Record<string, number>;
  architecture_hints: string[];
  entry_points: string[];
  largest_modules: LargestModule[];
  dependency_hotspots: DependencyHotspot[];
  created_at: string;
  updated_at: string;
}

export interface GraphEdge {
  source: string;
  target: string;
}

export interface CallGraphData {
  repository_id: string;
  nodes: string[];
  edges: GraphEdge[];
}

export interface DependencyGraphData {
  repository_id: string;
  nodes: string[];
  edges: GraphEdge[];
  circular_dependencies: string[][];
  orphan_files: string[];
}

export interface SymbolExplorerItem {
  id: string;
  file_id: string;
  file_path: string;
  parent_symbol_id: string | null;
  name: string;
  qualified_name: string;
  symbol_type: string;
  visibility: string;
  start_line: number;
  end_line: number;
  signature: string | null;
}

export interface SymbolExplorerData {
  repository_id: string;
  symbols: SymbolExplorerItem[];
}
