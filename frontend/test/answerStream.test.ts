import { describe, expect, it, vi } from "vitest";
import { createSyntheticAnswerStream } from "@/lib/answerStream";
import type { AskResponseData } from "@/lib/types/ai";

function buildResponse(answer: string): AskResponseData {
  return {
    repository_id: "repo-1",
    query: "where is auth",
    answer,
    evidence: [
      {
        file_path: "app/auth/routes.py",
        symbol_name: "login",
        symbol_type: "function",
        start_line: 14,
        end_line: 52,
        retrieval_score: 0.9,
        retrieval_sources: ["semantic"],
      },
    ],
    relevant_files: ["app/auth/routes.py"],
    relevant_symbols: ["login"],
    verification: { status: "supported", reasons: [] },
    metadata: {
      intent: "implementation",
      provider: "groq",
      model: "oss-120b",
      cache_hit: false,
      retry_count: 0,
      stage_latency_ms: {
        intent_ms: 5,
        retrieval_ms: 100,
        evidence_selection_ms: 20,
        context_construction_ms: 10,
        llm_ms: 500,
        verification_ms: 15,
        formatting_ms: 5,
        total_ms: 655,
      },
      retrieval_candidates: 12,
    },
  };
}

describe("createSyntheticAnswerStream", () => {
  it("fires onCitations/onVerification immediately, then reveals tokens, then onDone with the full response", async () => {
    const response = buildResponse("Authentication lives in app auth routes.");
    const events: string[] = [];
    let fullText = "";

    const stream = createSyntheticAnswerStream(
      () => Promise.resolve(response),
      {
        onCitations: () => events.push("citations"),
        onVerification: () => events.push("verification"),
        onToken: (_tok, soFar) => {
          events.push("token");
          fullText = soFar;
        },
        onDone: () => events.push("done"),
      },
      { msPerToken: 0 },
    );

    await stream.start();

    expect(events[0]).toBe("citations");
    expect(events[1]).toBe("verification");
    expect(events.filter((e) => e === "token").length).toBeGreaterThan(0);
    expect(events[events.length - 1]).toBe("done");
    expect(fullText).toBe(response.answer);
  });

  it("reassembles the full answer text byte-for-byte from its token chunks", async () => {
    const response = buildResponse("one two three four five");
    let finalText = "";
    const stream = createSyntheticAnswerStream(() => Promise.resolve(response), {
      onToken: (_tok, soFar) => {
        finalText = soFar;
      },
    }, { msPerToken: 0 });

    await stream.start();
    expect(finalText).toBe(response.answer);
  });

  it("calls onError instead of onDone when the fetch rejects", async () => {
    const onError = vi.fn();
    const onDone = vi.fn();
    const stream = createSyntheticAnswerStream(() => Promise.reject(new Error("boom")), { onError, onDone });

    await stream.start();

    expect(onError).toHaveBeenCalledTimes(1);
    expect(onDone).not.toHaveBeenCalled();
  });

  it("stops emitting further tokens after cancel() is called mid-stream", async () => {
    const response = buildResponse("alpha beta gamma delta epsilon zeta");
    let tokenCount = 0;
    const stream = createSyntheticAnswerStream(
      () => Promise.resolve(response),
      { onToken: () => (tokenCount += 1) },
      { msPerToken: 5 },
    );

    const done = stream.start();
    await new Promise((r) => setTimeout(r, 8));
    stream.cancel();
    await done;

    const countAtCancel = tokenCount;
    await new Promise((r) => setTimeout(r, 30));
    expect(tokenCount).toBe(countAtCancel);
  });
});
