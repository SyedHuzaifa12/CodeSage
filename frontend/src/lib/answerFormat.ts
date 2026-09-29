import type { Citation } from "@/lib/types/ai";

/**
 * Turns an Ask answer (LLM prose, light Markdown) into render blocks whose
 * code-like artifacts are linked to the evidence the answer actually cited.
 *
 * Linking is conservative and mirrors the backend's own verification
 * extraction (ai/engine/verification.py): a file path or `symbol()` only
 * becomes clickable when it matches an item in `evidence`. Nothing is
 * invented — an unmatched artifact still renders styled, just not linked.
 */

export type Inline =
  | { kind: "text"; text: string }
  | { kind: "strong"; children: Inline[] }
  | { kind: "art"; text: string; variant: "path" | "sym" | "plain"; cite: number | null }
  | { kind: "lines"; text: string };

export type Block = { kind: "p"; inlines: Inline[] } | { kind: "ul" | "ol"; items: Inline[][] };

const FILE_EXT =
  "py|pyi|js|jsx|mjs|cjs|ts|tsx|java|kt|go|rs|rb|php|c|h|cpp|cc|cs|json|ya?ml|toml|md|mdx|txt|cfg|ini|sql|html?|css|xml|sh";
const PATH_RE = new RegExp(`^[\\w][\\w\\-./]*\\.(?:${FILE_EXT})$`);
// Tokens scanned outside backticks: bare file paths, symbol() calls, line ranges, **bold**.
const SCAN_RE = new RegExp(
  `(\\*\\*[^*]+\\*\\*)|\`([^\`]+)\`|(\\b[\\w][\\w\\-./]*\\.(?:${FILE_EXT})\\b)|(\\b[A-Za-z_][\\w.]*\\(\\))|(\\blines? \\d+(?:\\s*(?:[-–—]|to)\\s*\\d+)?)`,
  "g",
);

export function matchPath(text: string, evidence: Citation[]): number | null {
  const idx = evidence.findIndex(
    (e) => e.file_path === text || e.file_path.endsWith(`/${text}`) || text.endsWith(`/${e.file_path}`),
  );
  return idx >= 0 ? idx : null;
}

export function matchSymbol(text: string, evidence: Citation[]): number | null {
  const bare = text.replace(/\(\)$/, "");
  const last = bare.split(".").pop() ?? bare;
  const idx = evidence.findIndex((e) => e.symbol_name === bare || e.symbol_name === last);
  return idx >= 0 ? idx : null;
}

function artifact(raw: string, evidence: Citation[]): Inline {
  const text = raw.trim();
  if (PATH_RE.test(text) || text.includes("/")) {
    return { kind: "art", text, variant: "path", cite: matchPath(text, evidence) };
  }
  const cite = matchSymbol(text, evidence);
  const looksSymbol = /\(\)$/.test(text) || /^[A-Za-z_][\w.]*$/.test(text);
  return { kind: "art", text, variant: looksSymbol ? "sym" : "plain", cite };
}

export function parseInline(line: string, evidence: Citation[]): Inline[] {
  const out: Inline[] = [];
  let last = 0;
  // A fresh regex per call: the **bold** branch recurses, and a shared
  // global regex would have its lastIndex reset mid-scan (infinite loop).
  const re = new RegExp(SCAN_RE.source, "g");
  let m: RegExpExecArray | null;
  while ((m = re.exec(line))) {
    if (m.index > last) out.push({ kind: "text", text: line.slice(last, m.index) });
    if (m[1]) out.push({ kind: "strong", children: parseInline(m[1].slice(2, -2), evidence) });
    else if (m[2] !== undefined) out.push(artifact(m[2], evidence));
    else if (m[3]) out.push({ kind: "art", text: m[3], variant: "path", cite: matchPath(m[3], evidence) });
    else if (m[4]) out.push({ kind: "art", text: m[4], variant: "sym", cite: matchSymbol(m[4], evidence) });
    else if (m[5]) out.push({ kind: "lines", text: m[5] });
    last = m.index + m[0].length;
  }
  if (last < line.length) out.push({ kind: "text", text: line.slice(last) });
  return out;
}

/**
 * LLM typography cleanup: narrow/no-break spaces and non-breaking hyphens
 * collapse visually in monospace ("lines115‑122"), and some models wrap
 * citations in 【…】 lenticular brackets. Content is otherwise untouched.
 */
export function normalizeAnswer(text: string): string {
  return text
    .replace(/\r\n/g, "\n")
    .replace(/[    ]/g, " ")
    .replace(/[‐‑]/g, "-")
    .replace(/[ \t]*【[ \t]*/g, " (")
    .replace(/[ \t]*】/g, ")");
}

export function parseAnswer(text: string, evidence: Citation[]): Block[] {
  const blocks: Block[] = [];
  const lines = normalizeAnswer(text).split("\n");
  let para: string[] = [];
  let list: { kind: "ul" | "ol"; items: Inline[][] } | null = null;
  const flushPara = () => {
    if (para.length) blocks.push({ kind: "p", inlines: parseInline(para.join(" "), evidence) });
    para = [];
  };
  const flushList = () => {
    if (list) blocks.push(list);
    list = null;
  };
  for (const raw of lines) {
    const line = raw.trim();
    const bullet = line.match(/^[-*•]\s+(.*)$/);
    const numbered = line.match(/^\d+[.)]\s+(.*)$/);
    if (!line) {
      flushPara();
      flushList();
      continue;
    }
    if (bullet || numbered) {
      flushPara();
      const kind = bullet ? "ul" : "ol";
      if (!list || list.kind !== kind) {
        flushList();
        list = { kind, items: [] };
      }
      list.items.push(parseInline((bullet ?? numbered)![1], evidence));
      continue;
    }
    flushList();
    // Headings from Markdown collapse to a bold paragraph lead-in.
    const heading = line.match(/^#{1,6}\s+(.*)$/);
    para.push(heading ? `**${heading[1]}**` : line);
  }
  flushPara();
  flushList();
  return blocks;
}

/** Strips Markdown syntax for the plain-text progressive reveal. */
export function plainText(text: string): string {
  return normalizeAnswer(text).replace(/\*\*([^*]+)\*\*/g, "$1").replace(/`([^`]+)`/g, "$1").replace(/^#{1,6}\s+/gm, "");
}
