"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowRight, Flame, Folder, LogIn, RotateCw, X } from "lucide-react";
import { groupLabelOf, topByDependents, type GraphData, type ModuleKind, type ModuleInfo, type Tangle } from "@/lib/graph/model";
import type { SymbolExplorerItem } from "@/lib/types/workspace";

export type GraphKind = "dependency" | "call";

const WORDS = {
  dependency: { unit: "module", units: "modules", edge: "import", uses: "Imports", usedBy: "Imported by", verb: "imports" },
  call: { unit: "symbol", units: "symbols", edge: "call", uses: "Calls", usedBy: "Called by", verb: "calls" },
} as const;
export const wordsFor = (k: GraphKind) => WORDS[k];

// ---------------------------------------------------------------------------------------------------------------------
// Key: what the shapes and lines mean
// ---------------------------------------------------------------------------------------------------------------------

export function GraphKey({ kind, hasTangles }: { kind: GraphKind; hasTangles: boolean }) {
  const w = WORDS[kind];
  return (
    <ul className="flex flex-wrap items-center gap-x-[18px] gap-y-1.5 text-[12px] text-text-secondary" aria-label="Map key">
      <li className="inline-flex items-center gap-1.5">
        <Folder size={14} className="text-violet" aria-hidden="true" />
        folder: click to open or close
      </li>
      <li className="inline-flex items-center gap-1.5">
        <i className="inline-block h-[18px] w-[34px] rounded-[5px] border border-border-strong bg-surface-1" aria-hidden="true" />
        {w.unit}
      </li>
      <li className="inline-flex items-center gap-1.5">
        <svg width="30" height="10" aria-hidden="true">
          <line x1="1" y1="5" x2="22" y2="5" stroke="currentColor" strokeWidth="1.5" />
          <path d="M22 1l6 4-6 4z" fill="currentColor" />
        </svg>
        {w.verb} (arrow points to what is {kind === "call" ? "called" : "used"})
      </li>
      <li className="inline-flex items-center gap-1.5">
        <span className="rounded bg-surface-3 px-1 py-[1px] font-mono text-[10px] text-text-tertiary">12</span>
        used by 12 others
      </li>
      <li className="inline-flex items-center gap-1.5">
        <Flame size={13} className="text-violet" aria-hidden="true" />
        hotspot: many depend on it
      </li>
      {kind === "dependency" && (
        <li className="inline-flex items-center gap-1.5">
          <LogIn size={13} className="text-info" aria-hidden="true" />
          entry point
        </li>
      )}
      {hasTangles && (
        <li className="inline-flex items-center gap-1.5">
          <svg width="30" height="10" aria-hidden="true">
            <line x1="1" y1="5" x2="28" y2="5" stroke="var(--cs-danger)" strokeWidth="1.6" strokeDasharray="5 4" />
          </svg>
          <RotateCw size={11} className="text-danger" aria-hidden="true" />
          circular: they depend on each other
        </li>
      )}
    </ul>
  );
}

// ---------------------------------------------------------------------------------------------------------------------
// Summary: what the picture says, in words
// ---------------------------------------------------------------------------------------------------------------------

export function GraphSummary({
  kind,
  data,
  kinds,
  tangles,
  entries,
  unconnected,
  hidden,
  onPick,
  onShowList,
}: {
  kind: GraphKind;
  data: GraphData;
  kinds: ReadonlySet<ModuleKind>;
  tangles: Tangle[];
  entries: ModuleInfo[];
  unconnected: number;
  hidden: { tests: number; external: number };
  onPick: (moduleId: string) => void;
  onShowList: () => void;
}) {
  const w = WORDS[kind];
  const key = topByDependents(data, kinds, 6);
  const shown = data.modules.filter((m) => kinds.has(m.kind)).length;
  const edgeCount = data.edges.filter((e) => kinds.has(data.byId.get(e.source)!.kind) && kinds.has(data.byId.get(e.target)!.kind)).length;
  return (
    <div>
      <p className="cs-mono-label">How to read this</p>
      <p className="mt-2 text-small leading-relaxed text-text-secondary">
        {kind === "dependency"
          ? "Each box is a folder or a file of the project. An arrow from A to B means A imports B, so A needs B to work. Folders open to show what is inside; click any file to see what it uses and what uses it."
          : "Each box is a function, class or method. An arrow from A to B means A calls B. Folders group symbols by the file they live in; click any symbol to see its callers and callees."}
      </p>
      <p className="cs-monoline mt-3 !text-[11px]">
        {shown.toLocaleString("en-US")} {w.units} · {edgeCount.toLocaleString("en-US")} {w.edge}s
      </p>

      {key.length > 0 && (
        <>
          <p className="cs-mono-label mt-7">{kind === "dependency" ? "Key modules: read these first" : "Most called"}</p>
          <p className="mt-1 text-[12px] text-text-tertiary">The most depended-on {w.units}. Changing one affects the most code.</p>
          <ul className="mt-2">
            {key.map((m) => (
              <li key={m.id}>
                <button onClick={() => onPick(m.id)} className="flex w-full items-baseline gap-2 border-t border-border-subtle py-2 text-left hover:text-[var(--cs-accent-violet-hover)]">
                  <span className="min-w-0 flex-1 break-all font-mono text-[12px] text-text-primary">{m.id}</span>
                  <span className="flex-none text-[11px] text-text-tertiary">used by {m.inDegree}</span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      {entries.length > 0 && (
        <>
          <p className="cs-mono-label mt-7">Entry points</p>
          <p className="mt-1 text-[12px] text-text-tertiary">Where the program starts running.</p>
          <ul className="mt-2">
            {entries.map((m) => (
              <li key={m.id}>
                <button onClick={() => onPick(m.id)} className="flex w-full items-center gap-2 border-t border-border-subtle py-2 text-left font-mono text-[12px] text-text-primary hover:text-[var(--cs-accent-violet-hover)]">
                  <LogIn size={12} className="flex-none text-info" aria-hidden="true" />
                  <span className="break-all">{m.id}</span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      {kind === "dependency" && (
        <>
          <p className="cs-mono-label mt-7">Circular dependencies</p>
          {tangles.length === 0 ? (
            <p className="mt-2 text-small text-text-secondary">None found. Dependencies flow in one direction, which keeps the code easy to change.</p>
          ) : (
            <>
              <p className="mt-1 text-[12px] text-text-tertiary">Files that depend on each other in a loop are hard to change or test on their own.</p>
              <ul className="mt-2">
                {tangles.slice(0, 5).map((t) => (
                  <li key={t.index}>
                    <button onClick={() => onPick(t.members[0])} className="flex w-full items-start gap-2 border-t border-border-subtle py-2 text-left hover:text-[var(--cs-accent-violet-hover)]">
                      <RotateCw size={12} className="mt-[3px] flex-none text-danger" aria-hidden="true" />
                      <span className="min-w-0 text-[12px]">
                        <b className="font-medium text-text-primary">{t.members.length} modules</b> depend on each other
                        <span className="mt-0.5 block break-all font-mono text-text-tertiary">
                          {t.members.slice(0, 3).join(", ")}
                          {t.members.length > 3 ? ` +${t.members.length - 3} more` : ""}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
                {tangles.length > 5 && <li className="border-t border-border-subtle py-2 text-[12px] text-text-tertiary">+{tangles.length - 5} more groups</li>}
              </ul>
            </>
          )}
        </>
      )}

      {(unconnected > 0 || hidden.tests > 0 || hidden.external > 0) && (
        <>
          <p className="cs-mono-label mt-7">Not drawn</p>
          <ul className="mt-2 space-y-2 text-[12px] text-text-secondary">
            {unconnected > 0 && (
              <li>
                <b className="font-medium text-text-primary">{unconnected.toLocaleString("en-US")} standalone {unconnected === 1 ? w.unit : w.units}</b> are neither used by nor use anything else here (scripts, config, documentation, or code reached some other way).{" "}
                <button onClick={onShowList} className="cs-link cs-link-quiet !inline">
                  See them in the list
                </button>
              </li>
            )}
            {hidden.tests > 0 && (
              <li>
                <b className="font-medium text-text-primary">{hidden.tests.toLocaleString("en-US")} test or example {hidden.tests === 1 ? "file" : "files"}</b> are hidden. Turn on "Tests &amp; examples" above to include them.
              </li>
            )}
            {hidden.external > 0 && (
              <li>
                <b className="font-medium text-text-primary">{hidden.external.toLocaleString("en-US")} outside {hidden.external === 1 ? "package" : "packages"}</b> (libraries the project imports) are hidden. Turn on "Outside packages" above to include them.
              </li>
            )}
          </ul>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------------
// Inspector: one module
// ---------------------------------------------------------------------------------------------------------------------

function RelationList({ items, onPick }: { items: string[]; onPick: (id: string) => void }) {
  const [all, setAll] = useState(false);
  if (items.length === 0) return <p className="mt-1 text-small text-text-tertiary">None.</p>;
  const shown = all ? items : items.slice(0, 8);
  return (
    <ul className="mt-1.5">
      {shown.map((x) => (
        <li key={x}>
          <button onClick={() => onPick(x)} className="block w-full break-all border-t border-border-subtle py-[7px] text-left font-mono text-[12px] text-text-secondary hover:text-[var(--cs-accent-violet-hover)]">
            {x}
          </button>
        </li>
      ))}
      {items.length > 8 && (
        <li className="border-t border-border-subtle py-[7px]">
          <button onClick={() => setAll(!all)} className="cs-link cs-link-quiet">
            {all ? "Show fewer" : `Show all ${items.length}`}
          </button>
        </li>
      )}
    </ul>
  );
}

export function ModuleInspector({
  kind,
  data,
  module,
  file,
  symbols,
  tangle,
  isHotspot,
  isEntry,
  repositoryId,
  onPick,
  onClose,
}: {
  kind: GraphKind;
  data: GraphData;
  module: ModuleInfo;
  file: string | null;
  symbols: SymbolExplorerItem[];
  tangle: Tangle | null;
  isHotspot: boolean;
  isEntry: boolean;
  repositoryId: string;
  onPick: (id: string) => void;
  onClose: () => void;
}) {
  const w = WORDS[kind];
  const uses = data.dependsOn.get(module.id) ?? [];
  const usedBy = data.usedBy.get(module.id) ?? [];
  const question = kind === "call" ? `What calls ${module.label}()?` : `Which modules depend on ${file ?? module.id}?`;
  return (
    <div className="relative">
      <button onClick={onClose} aria-label="Close details" className="absolute right-0 top-0 grid h-8 w-8 place-items-center rounded-md text-text-tertiary hover:bg-surface-2 hover:text-text-primary">
        <X size={15} aria-hidden="true" />
      </button>
      <p className="cs-mono-label">{kind === "call" ? "Symbol" : "Module"}</p>
      <h2 className="mt-2 break-all pr-8 font-display text-[18px] font-semibold leading-snug text-text-primary">{module.label}</h2>
      <p className="mt-1 break-all font-mono text-[11.5px] text-text-tertiary">{file ?? module.id}</p>
      <p className="mt-1 text-[12px] text-text-tertiary">in {groupLabelOf(data, module)}</p>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {isEntry && <span className="cs-badge !bg-[var(--cs-info-tint)] !text-info">entry point</span>}
        {isHotspot && <span className="cs-badge !bg-[var(--cs-violet-tint)] !text-violet">hotspot</span>}
        {tangle && <span className="cs-badge !bg-[var(--cs-danger-tint)] !text-danger">in a loop of {tangle.members.length}</span>}
        {module.kind !== "source" && <span className="cs-badge">{module.kind === "external" ? "outside package" : module.kind}</span>}
      </div>
      {tangle && (
        <p className="mt-3 text-[12px] leading-relaxed text-text-secondary">
          This {w.unit} is part of a loop: {tangle.members.length} {w.units} that all depend on each other, directly or through others. Changing one can ripple through all of them.
        </p>
      )}

      <p className="mt-4 text-[13px] text-text-secondary">
        Used by <b className="text-text-primary">{usedBy.length}</b> · {w.uses.toLowerCase()} <b className="text-text-primary">{uses.length}</b>
      </p>
      <Link href={`/r/${repositoryId}/ask?q=${encodeURIComponent(question)}`} className="cs-link mt-3">
        ask about this {w.unit} <ArrowRight size={13} aria-hidden="true" />
      </Link>

      <p className="cs-mono-label mt-6">
        {w.usedBy} · {usedBy.length}
      </p>
      <RelationList items={usedBy} onPick={onPick} />
      <p className="cs-mono-label mt-6">
        {w.uses} · {uses.length}
      </p>
      <RelationList items={uses} onPick={onPick} />

      <p className="cs-mono-label mt-6">Symbols</p>
      <div className="mt-1.5">
        {symbols.length === 0 && <p className="text-small text-text-tertiary">No parsed symbols.</p>}
        {symbols.slice(0, 15).map((s) => (
          <Link key={s.id} href={`/r/${repositoryId}/explorer?file=${encodeURIComponent(s.file_path)}&line=${s.start_line}`} className="block border-t border-border-subtle py-[7px] font-mono text-[12px] hover:bg-surface-1">
            <span className="text-violet">{s.name}</span> <span className="text-text-tertiary">{s.symbol_type} · {s.start_line}–{s.end_line}</span>
          </Link>
        ))}
        {symbols.length > 15 && <p className="border-t border-border-subtle py-[7px] font-mono text-[12px] text-text-tertiary">+{symbols.length - 15} more in Explorer</p>}
      </div>
      {file && (
        <Link href={`/r/${repositoryId}/explorer?file=${encodeURIComponent(file)}`} className="cs-link cs-link-quiet mt-4">
          open file in Explorer <ArrowRight size={13} aria-hidden="true" />
        </Link>
      )}
    </div>
  );
}
