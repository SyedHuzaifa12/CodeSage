"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { workspaceApi } from "@/lib/api/workspace";
import { queryKeys } from "@/lib/query/keys";

export function useWorkspace(id: string | undefined, opts?: { poll?: boolean }) {
  return useQuery({
    queryKey: queryKeys.workspace(id ?? ""),
    queryFn: () => workspaceApi.get(id as string),
    enabled: Boolean(id),
    refetchInterval: opts?.poll ? 2_000 : false,
  });
}

export function useTree(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.tree(id ?? ""),
    queryFn: () => workspaceApi.tree(id as string),
    enabled: Boolean(id),
  });
}

export function useIntelligence(id: string | undefined, opts?: { enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.intelligence(id ?? ""),
    queryFn: () => workspaceApi.intelligence(id as string),
    enabled: Boolean(id) && (opts?.enabled ?? true),
  });
}

export function useCallGraph(id: string | undefined, opts?: { enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.callGraph(id ?? ""),
    queryFn: () => workspaceApi.callGraph(id as string),
    enabled: Boolean(id) && (opts?.enabled ?? true),
  });
}

export function useDependencyGraph(id: string | undefined, opts?: { enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.dependencyGraph(id ?? ""),
    queryFn: () => workspaceApi.dependencyGraph(id as string),
    enabled: Boolean(id) && (opts?.enabled ?? true),
  });
}

export function useSymbols(id: string | undefined, opts?: { enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.symbols(id ?? ""),
    queryFn: () => workspaceApi.symbols(id as string),
    enabled: Boolean(id) && (opts?.enabled ?? true),
  });
}

export function useTriggerIndex() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => workspaceApi.triggerIndex(id),
    onSuccess: (_data, id) => client.invalidateQueries({ queryKey: queryKeys.repository(id) }),
  });
}

export function useRefreshWorkspace() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => workspaceApi.refresh(id),
    onSuccess: (_data, id) => client.invalidateQueries({ queryKey: queryKeys.workspace(id) }),
  });
}

export function useResetWorkspace() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => workspaceApi.reset(id),
    onSuccess: (_data, id) => {
      client.invalidateQueries({ queryKey: ["repositories", id] });
      client.invalidateQueries({ queryKey: queryKeys.repositories() });
    },
  });
}
