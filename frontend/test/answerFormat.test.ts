import { describe, expect, it } from "vitest";
import { parseAnswer, plainText } from "@/lib/answerFormat";
import type { Citation } from "@/lib/types/ai";

const evidence: Citation[] = [
  { file_path: "app/auth/routes.py", symbol_name: "login", symbol_type: "function", start_line: 10, end_line: 30, retrieval_score: 0.8, retrieval_sources: ["semantic"] },
];

describe("parseAnswer", () => {
  it("links only artifacts that match cited evidence", () => {
    const [block] = parseAnswer("See `app/auth/routes.py` and `other.py`, then login() on lines 10-30.", evidence);
    expect(block.kind).toBe("p");
    const arts = block.kind === "p" ? block.inlines.filter((i) => i.kind === "art") : [];
    expect(arts).toEqual([
      { kind: "art", text: "app/auth/routes.py", variant: "path", cite: 0 },
      { kind: "art", text: "other.py", variant: "path", cite: null },
      { kind: "art", text: "login()", variant: "sym", cite: 0 },
    ]);
    expect(block.kind === "p" && block.inlines.some((i) => i.kind === "lines")).toBe(true);
  });

  it("builds paragraphs and lists", () => {
    const blocks = parseAnswer("# Title\nIntro\n\n- one\n- two\n1. first", []);
    expect(blocks.map((b) => b.kind)).toEqual(["p", "ul", "ol"]);
    expect(blocks[0].kind === "p" && blocks[0].inlines[0].kind).toBe("strong");
  });

  it("strips markdown for the progressive reveal", () => {
    expect(plainText("## H\n**bold** `code`")).toBe("H\nbold code");
  });
});

describe("normalizeAnswer", () => {
  it("fixes LLM typography without changing content", async () => {
    const { normalizeAnswer } = await import("@/lib/answerFormat");
    expect(normalizeAnswer("See【 README.md, lines\u202f115\u2011122】.")).toBe("See (README.md, lines 115-122).");
  });
});
