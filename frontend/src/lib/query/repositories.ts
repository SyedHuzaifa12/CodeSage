"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { repositoriesApi } from "@/lib/api/repositories";
import { queryKeys } from "@/lib/query/keys";
import { isRepositoryReady, isRepositoryFailed, type RepositoryCreateRequest } from "@/lib/types/repository";

export function useRepositories() {
  return useQuery({
    queryKey: queryKeys.repositories(),
    queryFn: repositoriesApi.list,
    staleTime: 5_000,
  });
}

/** Polls every 2s while a repository is still onboarding (Design System §4) — stops once ready/failed. */
export function useRepository(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.repository(id ?? ""),
    queryFn: () => repositoriesApi.get(id as string),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      const repo = query.state.data;
      if (!repo) return false;
      if (isRepositoryReady(repo) || isRepositoryFailed(repo)) return false;
      return 2_000;
    },
  });
}

export function useCreateRepository() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: RepositoryCreateRequest) => repositoriesApi.create(payload),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.repositories() }),
  });
}

export function useDeleteRepository() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => repositoriesApi.delete(id),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.repositories() }),
  });
}

export function useUpdateRepositoryName() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => repositoriesApi.update(id, { name }),
    onSuccess: (_data, vars) => {
      client.invalidateQueries({ queryKey: queryKeys.repository(vars.id) });
      client.invalidateQueries({ queryKey: queryKeys.repositories() });
    },
  });
}
