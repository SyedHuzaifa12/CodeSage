"use client";

import { useQuery } from "@tanstack/react-query";
import { authApi } from "@/lib/api/auth";
import { queryKeys } from "@/lib/query/keys";

/**
 * The caller's identity and quota usage. The first call also bootstraps the
 * session (creating a guest if there is none), so this is what makes a first
 * visit "just work". `enabled` lets the OAuth callback page opt out, because
 * it is about to replace the session and must not create a throwaway guest.
 */
export function useMe(enabled = true) {
  return useQuery({
    queryKey: queryKeys.me(),
    queryFn: authApi.me,
    enabled,
    staleTime: 15_000,
    retry: 1,
  });
}
