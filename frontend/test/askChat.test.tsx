import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AskTurnView } from "@/components/ask/AskTurnView";
import { Composer } from "@/components/ask/Composer";
import { EmptyChat } from "@/components/ask/EmptyChat";
import { ThinkingSteps } from "@/components/ask/ThinkingSteps";
import type { AskTurn } from "@/lib/askSession";
import type { AskResponseData, Citation } from "@/lib/types/ai";

afterEach(cleanup);

describe("Composer", () => {
  const setup = (props: Partial<Parameters<typeof Composer>[0]> = {}) => {
    const handlers = { onChange: vi.fn(), onSubmit: vi.fn(), onStop: vi.fn(), onToggleOptions: vi.fn() };
    render(<Composer value="How does auth work?" busy={false} optionsOpen={false} optionsActive={false} {...handlers} {...props} />);
    return { ...handlers, box: screen.getByRole("textbox") };
  };

  it("sends on Enter", () => {
    const { box, onSubmit } = setup();
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledOnce();
  });

  it("adds a line on Shift+Enter instead of sending", () => {
    const { box, onSubmit } = setup();
    fireEvent.keyDown(box, { key: "Enter", shiftKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("never sends in the middle of an IME composition (it would eat a half-typed word)", () => {
    const { box, onSubmit } = setup();
    fireEvent.keyDown(box, { key: "Enter", isComposing: true });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("does not send an empty or whitespace-only message", () => {
    const { box, onSubmit } = setup({ value: "   " });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onSubmit).not.toHaveBeenCalled();
    expect((screen.getByRole("button", { name: /send question/i }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("does not send while retrieval is blocked (no sources selected)", () => {
    const { box, onSubmit } = setup({ blocked: true });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("turns Send into Stop while an answer is being written, and Enter does not send a second question", () => {
    const { box, onSubmit, onStop } = setup({ busy: true });
    expect(screen.queryByRole("button", { name: /send question/i })).toBeNull();
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onSubmit).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /stop generating/i }));
    expect(onStop).toHaveBeenCalledOnce();
  });

  it("sends with the button", () => {
    const { onSubmit } = setup();
    fireEvent.click(screen.getByRole("button", { name: /send question/i }));
    expect(onSubmit).toHaveBeenCalledOnce();
  });

  it("limits the message length and reports typing", () => {
    const { box, onChange } = setup({ value: "" });
    expect(box.getAttribute("maxlength")).toBe("4000");
    fireEvent.change(box, { target: { value: "hi" } });
    expect(onChange).toHaveBeenCalledWith("hi");
  });

  it("marks the options button when options are customised, and toggles them", () => {
    const { onToggleOptions } = setup({ optionsActive: true });
    expect(screen.getByLabelText(/custom options on/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /retrieval options/i }));
    expect(onToggleOptions).toHaveBeenCalledOnce();
  });
});

describe("ThinkingSteps", () => {
  it("names the step in progress and lists every step", () => {
    render(<ThinkingSteps stage={2} startedAt={Date.now()} onCancel={vi.fn()} />);
    expect(screen.getByRole("status").textContent).toContain("Writing the answer…");
    expect(screen.getAllByRole("listitem")).toHaveLength(4);
  });

  it("clamps a stage beyond the last step instead of crashing", () => {
    render(<ThinkingSteps stage={9} startedAt={Date.now()} onCancel={vi.fn()} />);
    expect(screen.getByRole("status").textContent).toContain("Checking it against the sources…");
  });

  it("lets the user stop it", () => {
    const onCancel = vi.fn();
    render(<ThinkingSteps stage={0} startedAt={Date.now()} onCancel={onCancel} />);
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(onCancel).toHaveBeenCalledOnce();
  });
});

describe("EmptyChat", () => {
  it("names the repository and offers at most four starting questions", () => {
    const onPick = vi.fn();
    render(<EmptyChat repositoryName="Express" symbolCount={1234} suggestions={["a one", "b two", "c three", "d four", "e five"]} onPick={onPick} />);
    expect(screen.getByRole("heading").textContent).toBe("Ask about Express");
    expect(screen.getByText(/1,234 indexed symbols/)).toBeTruthy();
    expect(screen.queryByText("e five")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /b two/ }));
    expect(onPick).toHaveBeenCalledWith("b two");
  });
});

const citation = (path: string, start: number | null = 10, end: number | null = 20): Citation => ({
  file_path: path,
  symbol_name: "handler",
  symbol_type: "function",
  start_line: start,
  end_line: end,
  retrieval_score: 0.5,
  retrieval_sources: ["semantic"],
});

function response(over: Partial<AskResponseData> = {}): AskResponseData {
  return {
    repository_id: "r1",
    query: "q",
    answer: "It is **handled** in `errors.py`.",
    explanation: null,
    evidence: [citation("app/api/errors.py"), citation("app/errors/__init__.py", 3, 3), citation("app/api/__init__.py", 3, 3)],
    relevant_files: ["app/api/errors.py"],
    relevant_symbols: [],
    verification: { status: "supported", reasons: ["All 2 citations verified."] },
    metadata: {
      intent: "implementation",
      provider: "groq",
      model: "m",
      cache_hit: false,
      retry_count: 0,
      retrieval_candidates: 9,
      stage_latency_ms: { intent_ms: 1, retrieval_ms: 2, evidence_selection_ms: 3, context_construction_ms: 4, llm_ms: 5, verification_ms: 6, formatting_ms: 7, total_ms: 28 },
    },
    ...over,
  };
}

const turn = (over: Partial<AskTurn> = {}): AskTurn => ({
  id: "t1",
  question: "How are errors handled?",
  stage: 4,
  status: "done",
  partial: "",
  response: response(),
  error: null,
  askedAt: Date.now(),
  ...over,
});

describe("AskTurnView", () => {
  const handlers = () => ({ onHover: vi.fn(), onCite: vi.fn(), onRetry: vi.fn(), onCancel: vi.fn(), onFollowUp: vi.fn() });
  const view = (t: AskTurn, h = handlers()) => {
    render(<AskTurnView turn={t} hovered={null} {...h} />);
    return h;
  };

  beforeEach(() => {
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
  });

  it("shows the question and a finished answer with its sources, verification and actions", () => {
    view(turn());
    expect(screen.getByText("How are errors handled?")).toBeTruthy();
    expect(screen.getByText("Sources (3)")).toBeTruthy();
    expect(screen.getByText("Primary")).toBeTruthy();
    expect(screen.getByText("All 2 citations verified.")).toBeTruthy();
    expect(screen.getByRole("button", { name: /regenerate/i })).toBeTruthy();
  });

  it("tells same-named source files apart by showing their folder", () => {
    view(turn());
    expect(screen.getByRole("button", { name: /source 2: app\/errors\/__init__\.py:3/i }).textContent).toContain("errors/__init__.py");
    expect(screen.getByRole("button", { name: /source 3: app\/api\/__init__\.py:3/i }).textContent).toContain("api/__init__.py");
  });

  it("opens the evidence for a clicked source", () => {
    const h = view(turn());
    fireEvent.click(screen.getByRole("button", { name: /source 2/i }));
    expect(h.onCite).toHaveBeenCalledWith(1);
  });

  it("collapses a long source list behind '+N more' and can expand it", () => {
    const many = Array.from({ length: 7 }, (_, i) => citation(`src/f${i}.py`));
    view(turn({ response: response({ evidence: many }) }));
    expect(screen.getAllByRole("button", { name: /^Source \d/ })).toHaveLength(4);

    fireEvent.click(screen.getByRole("button", { name: "+3 more" }));
    expect(screen.getAllByRole("button", { name: /^Source \d/ })).toHaveLength(7);
    fireEvent.click(screen.getByRole("button", { name: "Show fewer" }));
    expect(screen.getAllByRole("button", { name: /^Source \d/ })).toHaveLength(4);
  });

  it("copies the answer as plain text, without markdown markers", async () => {
    view(turn());
    fireEvent.click(screen.getByRole("button", { name: /copy/i }));
    await screen.findByText("Copied");
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("It is handled in errors.py.");
  });

  it("regenerates and offers related questions drawn from the answer's files", () => {
    const h = view(turn({ response: response({ relevant_files: ["app/api/auth.py"] }) }));
    fireEvent.click(screen.getByRole("button", { name: /regenerate/i }));
    expect(h.onRetry).toHaveBeenCalledOnce();

    fireEvent.click(screen.getByRole("button", { name: "Explain app/api/auth.py" }));
    expect(h.onFollowUp).toHaveBeenCalledWith("Explain app/api/auth.py");
  });

  it("explains an unsupported answer and suggests a better question instead of related ones", () => {
    view(turn({ response: response({ verification: { status: "insufficient_evidence", reasons: ["Not enough evidence."] }, relevant_files: ["a.py"] }) }));
    expect(screen.getByText(/try naming a specific file/i)).toBeTruthy();
    expect(screen.queryByText("Related questions")).toBeNull();
  });

  it("says plainly when nothing in the index was relevant", () => {
    view(turn({ response: response({ evidence: [] }) }));
    expect(screen.getByText(/no citations/i)).toBeTruthy();
  });

  it("shows the progress steps while working, and stops on request", () => {
    const h = view(turn({ status: "thinking", stage: 1, response: null }));
    expect(screen.getByRole("status").textContent).toContain("Selecting the best evidence…");
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(h.onCancel).toHaveBeenCalledOnce();
  });

  it("shows the text so far while it is being written", () => {
    view(turn({ status: "revealing", partial: "It starts here", response: null }));
    expect(screen.getByText(/It starts here/)).toBeTruthy();
  });

  it("treats a user stop as neutral and offers to ask again, not as a failure", () => {
    const h = view(turn({ status: "error", response: null, error: new Error("Cancelled.") }));
    expect(screen.getByText("Stopped")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /ask again/i }));
    expect(h.onRetry).toHaveBeenCalledOnce();
  });

  it("shows a real failure with the error and a retry", () => {
    const h = view(turn({ status: "error", response: null, error: new Error("boom") }));
    expect(screen.getByText("Something went wrong answering this question")).toBeTruthy();
    expect(within(screen.getByRole("alert")).getByText("boom")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(h.onRetry).toHaveBeenCalledOnce();
  });
});
