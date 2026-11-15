type QuotaListener = (message: string) => void;

const quotaListeners = new Set<QuotaListener>();

/**
 * Tiny pub/sub that lets the API layer tell the UI "a guest just hit a limit
 * that signing in lifts" without the API client importing any React code.
 */
export const authEvents = {
  onQuotaExceeded(listener: QuotaListener): () => void {
    quotaListeners.add(listener);
    return () => quotaListeners.delete(listener);
  },
  emitQuotaExceeded(message: string): void {
    quotaListeners.forEach((listener) => listener(message));
  },
};
