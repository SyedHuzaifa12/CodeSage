import { api } from "@/lib/api/client";
import type { AskOptions, AskResponseData } from "@/lib/types/ai";

/** Mirrors backend/app/ai/api.py. Ask's 60s timeout accounts for the observed
 * up-to-29s cold multi-file synthesis latency documented in SPRINT_LOG.md. */
export const aiApi = {
  ask: (repositoryId: string, query: string, options?: AskOptions, signal?: AbortSignal) =>
    api.post<AskResponseData>(
      `/repositories/${repositoryId}/ask`,
      { query, options },
      { timeoutMs: 60_000, signal },
    ),
};
