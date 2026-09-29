import type { AskResponseData, Citation, VerificationInfo } from "@/lib/types/ai";

/**
 * True-streaming-compatible internal contract for Ask (Design System §13,
 * finalized decision). The Ask page's rendering layer consumes ONLY this
 * interface — never a single "answer arrived" callback — so a future real
 * backend SSE/streaming adapter can implement the same interface with zero
 * changes to any component above the adapter layer (message rendering,
 * citation chips, verification badge, reasoning ribbon, disclosure panel).
 */
export interface AnswerStreamHandlers {
  /** Fired once per synthetic/real token as the answer text becomes available. */
  onToken?: (tokenText: string, fullTextSoFar: string) => void;
  /** Fired once citations are known (today: immediately, from the complete response). */
  onCitations?: (citations: Citation[]) => void;
  /** Fired once verification is known. */
  onVerification?: (verification: VerificationInfo) => void;
  /** Fired once the stream is fully complete, with the full response payload. */
  onDone?: (full: AskResponseData) => void;
  /** Fired if the stream/request fails at any point. */
  onError?: (error: Error) => void;
}

export interface AnswerStream {
  /** Begin consuming the stream — resolves once onDone/onError has fired. */
  start(): Promise<void>;
  /** Abort a stream in progress. */
  cancel(): void;
}

/**
 * Sprint 7 implementation: POST /ask returns one complete JSON response
 * (current, unchanged backend contract). This adapter fulfills the
 * AnswerStream contract by chunking the already-complete `answer` text into
 * a synthetic token stream (the Newsreader-italic progressive reveal), then
 * fires onCitations/onVerification/onDone from that same response — no
 * network streaming occurs. A future backend SSE endpoint would implement
 * AnswerStream directly against real per-token network events instead of
 * this setInterval loop; every consumer stays unchanged.
 */
export function createSyntheticAnswerStream(
  fetchAnswer: () => Promise<AskResponseData>,
  handlers: AnswerStreamHandlers,
  opts: { msPerToken?: number; wordsPerToken?: number } = {},
): AnswerStream {
  const msPerToken = opts.msPerToken ?? 18;
  const wordsPerToken = opts.wordsPerToken ?? 1;
  let cancelled = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let resolveTokenLoop: (() => void) | undefined;

  return {
    async start() {
      let response: AskResponseData;
      try {
        response = await fetchAnswer();
      } catch (err) {
        if (!cancelled) handlers.onError?.(err instanceof Error ? err : new Error(String(err)));
        return;
      }
      if (cancelled) return;

      handlers.onCitations?.(response.evidence);
      handlers.onVerification?.(response.verification);

      const words = response.answer.split(/(\s+)/); // keep whitespace tokens for natural spacing
      const chunks: string[] = [];
      for (let i = 0; i < words.length; i += wordsPerToken * 2) {
        chunks.push(words.slice(i, i + wordsPerToken * 2).join(""));
      }

      await new Promise<void>((resolve) => {
        resolveTokenLoop = resolve;
        let index = 0;
        let soFar = "";
        const step = () => {
          if (cancelled) {
            resolve();
            return;
          }
          if (index >= chunks.length) {
            resolve();
            return;
          }
          soFar += chunks[index];
          handlers.onToken?.(chunks[index], soFar);
          index += 1;
          timer = setTimeout(step, msPerToken);
        };
        step();
      });

      if (!cancelled) {
        handlers.onDone?.(response);
      }
    },
    cancel() {
      cancelled = true;
      if (timer) clearTimeout(timer);
      // clearTimeout above prevents `step` from ever running again, so the
      // token-loop promise would otherwise hang forever awaiting a resolve
      // that never comes — settle it immediately instead.
      resolveTokenLoop?.();
    },
  };
}
