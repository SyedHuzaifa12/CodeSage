"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { TooltipProvider } from "@/components/ui/Tooltip";
import { OfflineBanner } from "@/components/state/StateVocabulary";
import { API_BASE_URL } from "@/lib/api/client";

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: 1,
        refetchOnWindowFocus: false,
        staleTime: 10_000,
      },
    },
  });
}

let browserQueryClient: QueryClient | undefined;
function getQueryClient() {
  if (typeof window === "undefined") return makeQueryClient();
  if (!browserQueryClient) browserQueryClient = makeQueryClient();
  return browserQueryClient;
}

/** Workspace-level offline banner (§9.2): if the backend is unreachable, no page can do anything. */
function useBackendHealth() {
  const [online, setOnline] = useState(true);

  useEffect(() => {
    let cancelled = false;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout>;

    const check = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/health`, { cache: "no-store" });
        if (!cancelled) {
          setOnline(res.ok);
          attempt = res.ok ? 0 : attempt + 1;
        }
      } catch {
        if (!cancelled) {
          setOnline(false);
          attempt += 1;
        }
      }
      const backoff = Math.min(30_000, 3_000 * 2 ** attempt);
      timer = setTimeout(check, backoff);
    };

    void check();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  return { online, retry: () => window.location.reload() };
}

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(getQueryClient);
  const { online, retry } = useBackendHealth();

  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>
        {!online && <OfflineBanner onRetry={retry} />}
        {children}
      </TooltipProvider>
    </QueryClientProvider>
  );
}
