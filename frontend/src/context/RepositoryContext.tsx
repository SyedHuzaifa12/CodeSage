"use client";

import { createContext, useContext, type ReactNode } from "react";
import { useRepository } from "@/lib/query/repositories";
import type { Repository } from "@/lib/types/repository";
import { isRepositoryReady } from "@/lib/types/repository";

interface RepositoryContextValue {
  repositoryId: string;
  repository: Repository | undefined;
  isLoading: boolean;
  isError: boolean;
  isReady: boolean;
}

const RepositoryContext = createContext<RepositoryContextValue | null>(null);

/** Shared repository context (Design System §1/C): every per-repository page reads from this. */
export function RepositoryProvider({ repositoryId, children }: { repositoryId: string; children: ReactNode }) {
  const { data: repository, isLoading, isError } = useRepository(repositoryId);

  return (
    <RepositoryContext.Provider
      value={{
        repositoryId,
        repository,
        isLoading,
        isError,
        isReady: repository ? isRepositoryReady(repository) : false,
      }}
    >
      {children}
    </RepositoryContext.Provider>
  );
}

export function useRepositoryContext(): RepositoryContextValue {
  const ctx = useContext(RepositoryContext);
  if (!ctx) throw new Error("useRepositoryContext must be used within a RepositoryProvider");
  return ctx;
}
