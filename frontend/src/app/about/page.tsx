import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { TopBar } from "@/components/nav/TopBar";

export const metadata = { title: "How CodeSage works" };

const PIPELINE: { n: string; title: string; body: string }[] = [
  { n: "01", title: "Clone & scan", body: "A shallow clone of a public GitHub repository. The scan walks the clone, skips vendored and build folders, and classifies about 40 languages by extension (for statistics only)." },
  { n: "02", title: "Parse", body: "Tree-sitter extracts symbols (classes, interfaces, enums, functions, methods, variables, namespaces) and their imports, extends, implements and belongs-to relationships. Only Python, JavaScript, TypeScript and Java are parsed; if one file fails to parse, the rest still go through." },
  { n: "03", title: "Repository intelligence", body: "The dependency graph, entry points, hotspots (5 or more incoming dependencies), circular dependencies and orphan files. All of it is computed deterministically, without an LLM." },
  { n: "04", title: "Knowledge index", body: "Symbol-aware chunking (up to 3,500 characters) embedded locally with BAAI/bge-small-en-v1.5 into Qdrant. A reindex skips unchanged files by content hash." },
  { n: "05", title: "Hybrid retrieval", body: "Semantic, lexical (symbol names and paths) and structural (one-hop graph expansion) sources are fused with weights of 0.50 / 0.35 / 0.15. Every result shows why it matched. Cross-encoder reranking is optional." },
  { n: "06", title: "Grounded Ask", body: "Intent → retrieval → evidence selection (at most 8 items, 2 per file) → context → one LLM call → deterministic citation verification, with one bounded retry. The answer is returned in one response and revealed progressively in the UI." },
];

const LIMITS = [
  "Answers are single-turn. Earlier questions are not sent as context, and Ask history lasts only for this browser session.",
  "Only four languages are parsed. Files in other languages appear in statistics but have no symbols.",
  "Clones are never updated. To index newer code, delete the repository and add it again.",
  "Verification is a deterministic check that the citations match the evidence. It is not a probability, and CodeSage never shows a numeric confidence score.",
  "The graph shows only relationships the parser extracted. No edges are inferred.",
];

export default function AboutPage() {
  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <TopBar />
      <main className="cs-scrollbar min-h-0 flex-1 overflow-y-auto">
        <div className="cs-page cs-page-glow">
          <div className="relative z-10 mx-auto max-w-[760px] px-5 pb-24 pt-12 sm:px-8 sm:pt-14">
            <Link href="/" className="cs-link cs-link-quiet">
              <ArrowLeft size={13} aria-hidden="true" /> Repositories
            </Link>
            <p className="cs-mono-label mt-8">Under the hood</p>
            <h1 className="cs-masthead mt-2">How CodeSage works</h1>
            <p className="cs-lede mt-4">
              Everything CodeSage shows comes from the repository itself: parsed symbols, extracted relationships and retrieved source lines. AI writes the prose, and <b>deterministic code checks it</b>.
            </p>

            <ol className="m-0 mt-10 list-none border-t border-border-subtle p-0">
              {PIPELINE.map((s, i) => (
                <li key={s.n} className="grid grid-cols-[44px_minmax(0,1fr)] gap-3 border-b border-border-subtle py-5" style={{ animation: `cs-rise 520ms var(--cs-ease-out) ${i * 50}ms both` }}>
                  <span className="pt-0.5 font-mono text-[11px] font-medium tracking-[0.04em] text-violet">{s.n}</span>
                  <div>
                    <h2 className="font-sans text-[16px] font-semibold text-text-primary">{s.title}</h2>
                    <p className="mt-1.5 max-w-[62ch] text-[14px] leading-[1.7] text-text-secondary">{s.body}</p>
                  </div>
                </li>
              ))}
            </ol>

            <section className="mt-12" aria-labelledby="prov">
              <h2 id="prov" className="font-sans text-[17px] font-semibold text-text-primary">
                Provenance, at a glance
              </h2>
              <dl className="cs-kv mt-4">
                <dt>deterministic</dt>
                <dd>statistics, graph, hotspots, cycles, orphans, diagrams, most report sections</dd>
                <dt>AI-written</dt>
                <dd>Ask answers and a single narrative section per report, marked with an AI tag</dd>
                <dt>verified</dt>
                <dd>every citation is checked against the evidence that was selected</dd>
              </dl>
            </section>

            <section className="mt-12" aria-labelledby="lim">
              <h2 id="lim" className="font-sans text-[17px] font-semibold text-text-primary">
                Known limits
              </h2>
              <ul className="m-0 mt-3.5 list-none p-0">
                {LIMITS.map((l) => (
                  <li key={l} className="relative border-t border-border-subtle py-2.5 pl-[18px] text-[13.5px] text-text-secondary before:absolute before:left-0.5 before:top-[19px] before:h-[1.5px] before:w-[7px] before:bg-violet">
                    {l}
                  </li>
                ))}
              </ul>
            </section>
          </div>
        </div>
      </main>
    </div>
  );
}
