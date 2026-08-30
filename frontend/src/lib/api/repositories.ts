import { api } from "@/lib/api/client";
import type {
  Repository,
  RepositoryCreateRequest,
  RepositoryListData,
  RepositoryUpdateRequest,
} from "@/lib/types/repository";

/** Mirrors backend/app/repository/api.py exactly — one module, one client. */
export const repositoriesApi = {
  list: () => api.get<RepositoryListData>("/repositories"),
  get: (id: string) => api.get<Repository>(`/repositories/${id}`),
  create: (payload: RepositoryCreateRequest) => api.post<Repository>("/repositories", payload),
  update: (id: string, payload: RepositoryUpdateRequest) =>
    api.patch<Repository>(`/repositories/${id}`, payload),
  delete: (id: string) => api.delete<{ id: string }>(`/repositories/${id}`),
};
