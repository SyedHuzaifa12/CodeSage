/** Mirrors backend/app/repository/schemas.py and models/repository.py. */

export const REPOSITORY_STATUSES = ["pending", "cloning", "ready", "failed", "deleted"] as const;
export type RepositoryStatus = (typeof REPOSITORY_STATUSES)[number];

export const INDEXING_STATUSES = ["not_started", "indexing", "indexed", "failed"] as const;
export type IndexingStatus = (typeof INDEXING_STATUSES)[number];

export interface Repository {
  id: string;
  name: string;
  github_url: string | null;
  local_path: string;
  language: string | null;
  status: RepositoryStatus;
  indexing_status: IndexingStatus;
  indexing_progress: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface RepositoryListData {
  repositories: Repository[];
  total: number;
}

export interface RepositoryCreateRequest {
  github_url: string;
  name?: string;
}

export interface RepositoryUpdateRequest {
  name: string;
}

/** A repository is queryable (Ask/Search/Graph/Reports reachable) only in this state. */
export function isRepositoryReady(repo: Pick<Repository, "status" | "indexing_status">): boolean {
  return repo.status === "ready" && repo.indexing_status === "indexed";
}

export function isRepositoryFailed(repo: Pick<Repository, "status" | "indexing_status">): boolean {
  return repo.status === "failed" || repo.indexing_status === "failed";
}
