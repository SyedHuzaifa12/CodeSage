import { api } from "@/lib/api/client";
import type {
  Repository,
  RepositoryCreateRequest,
  RepositoryListData,
  RepositoryUpdateRequest,
} from "@/lib/types/repository";

/** A slow clone can outlive the client's patience; the row still appears afterwards (re-fetch on settle). */
export const CREATE_TIMEOUT_MS = 180_000;

/** Mirrors backend/app/repository/api.py exactly — one module, one client. */
export const repositoriesApi = {
  list: () => api.get<RepositoryListData>("/repositories"),
  get: (id: string) => api.get<Repository>(`/repositories/${id}`),
  /** Clone + file scan run synchronously inside this request, so it gets a long timeout. */
  create: (payload: RepositoryCreateRequest) =>
    api.post<Repository>("/repositories", payload, { timeoutMs: CREATE_TIMEOUT_MS }),
  update: (id: string, payload: RepositoryUpdateRequest) =>
    api.patch<Repository>(`/repositories/${id}`, payload),
  delete: (id: string) => api.delete<{ id: string }>(`/repositories/${id}`),
};
