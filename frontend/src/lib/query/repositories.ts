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
    // Always re-fetch: a failed clone (502) still persists a FAILED row, and
    // a client-side timeout can leave a clone that later completes. The
    // quota ("1 of 1 repositories used") changes either way.
    onSettled: () => {
      void client.invalidateQueries({ queryKey: queryKeys.repositories() });
      void client.invalidateQueries({ queryKey: queryKeys.me() });
    },
  });
}

export function useDeleteRepository() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => repositoriesApi.delete(id),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.repositories() });
      void client.invalidateQueries({ queryKey: queryKeys.me() }); // frees a repository slot
    },
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
