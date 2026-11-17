"use client";

import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Flame, LogIn, RotateCw } from "lucide-react";
import { groupLabelOf, type GraphData, type ModuleKind } from "@/lib/graph/model";
import { cn } from "@/lib/utils";

type SortKey = "name" | "usedBy" | "uses";
const PAGE = 100;

/**
 * The same graph as a table. A map is the wrong tool on a phone, for screen readers, and whenever the question is "which
 * module is the most depended on": a sortable list answers that exactly, and it is the only place the standalone files
 * (which a dependency map has no place for) can be browsed.
 */
export function ModuleTable({
  data,
  kinds,
  query,
  selected,
  tangleOf,
  hotspots,
  entries,
  unit,
  onSelect,
}: {
  data: GraphData;
  kinds: ReadonlySet<ModuleKind>;
  query: string;
  selected: string | null;
  tangleOf: ReadonlyMap<string, number>;
  hotspots: ReadonlySet<string>;
  entries: ReadonlySet<string>;
  unit: "module" | "symbol";
  onSelect: (id: string) => void;
}) {
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "usedBy", dir: -1 });
  const [limit, setLimit] = useState(PAGE);
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = data.modules.filter((m) => kinds.has(m.kind) && (!q || m.id.toLowerCase().includes(q)));
    const val = (m: (typeof list)[number]) => (sort.key === "usedBy" ? m.inDegree : sort.key === "uses" ? m.outDegree : 0);
    return list.sort((a, b) => (sort.key === "name" ? sort.dir * a.id.localeCompare(b.id) : sort.dir * (val(a) - val(b)) || a.id.localeCompare(b.id)));
  }, [data, kinds, query, sort]);

  const notes = (m: GraphData["modules"][number]) => (
    <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11.5px] text-text-tertiary">
      {entries.has(m.id) && (
        <span className="inline-flex items-center gap-1 text-info">
          <LogIn size={11} aria-hidden="true" />
          entry point
        </span>
      )}
      {hotspots.has(m.id) && (
        <span className="inline-flex items-center gap-1 text-violet">
          <Flame size={11} aria-hidden="true" />
          hotspot
        </span>
      )}
      {tangleOf.has(m.id) && (
        <span className="inline-flex items-center gap-1 text-danger">
          <RotateCw size={11} aria-hidden="true" />
          in a loop
        </span>
      )}
      {m.inDegree === 0 && m.outDegree === 0 && <span>standalone</span>}
      {m.kind !== "source" && <span>{m.kind === "external" ? "outside package" : m.kind}</span>}
    </span>
  );

  const head = (key: SortKey, label: string, align: "left" | "right" = "left") => (
    <th scope="col" aria-sort={sort.key === key ? (sort.dir === 1 ? "ascending" : "descending") : "none"} className={cn("px-3 py-2 font-medium", align === "right" && "text-right")}>
      <button
        onClick={() => setSort((s) => (s.key === key ? { key, dir: s.dir === 1 ? -1 : 1 } : { key, dir: key === "name" ? 1 : -1 }))}
        className={cn("inline-flex items-center gap-1 hover:text-text-primary", sort.key === key && "text-text-primary")}
      >
        {label}
        {sort.key === key && (sort.dir === 1 ? <ArrowUp size={11} aria-hidden="true" /> : <ArrowDown size={11} aria-hidden="true" />)}
      </button>
    </th>
  );

  return (
    <div className="cs-scrollbar h-full overflow-auto px-4 pb-10 pt-4 sm:px-6">
      <p className="mb-3 text-[12px] text-text-tertiary" role="status">
        {rows.length.toLocaleString("en-US")} {rows.length === 1 ? unit : `${unit}s`}
        {query.trim() ? ` matching "${query.trim()}"` : ""}. Click a column to sort.
      </p>
      <table className="w-full border-collapse text-left text-[12.5px]">
        <thead className="sticky top-0 bg-bg text-[11px] uppercase tracking-wide text-text-tertiary">
          <tr className="border-b border-border-subtle">
            {head("name", unit === "symbol" ? "Symbol" : "Module")}
            <th scope="col" className="hidden px-3 py-2 font-medium md:table-cell">
              Folder
            </th>
            {head("usedBy", "Used by", "right")}
            {head("uses", unit === "symbol" ? "Calls" : "Imports", "right")}
            <th scope="col" className="hidden px-3 py-2 font-medium md:table-cell">
              Notes
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, limit).map((m) => (
            <tr key={m.id} className={cn("border-b border-border-subtle", m.id === selected && "bg-[var(--cs-violet-tint)]")}>
              <td className="max-w-[360px] px-3 py-1.5">
                <button onClick={() => onSelect(m.id)} aria-pressed={m.id === selected} className="block max-w-full break-all text-left font-mono text-text-primary hover:text-[var(--cs-accent-violet-hover)]">
                  {m.id}
                </button>
                <span className="mt-0.5 block md:hidden">{notes(m)}</span>
              </td>
              <td className="hidden max-w-[200px] truncate px-3 py-1.5 font-mono text-text-tertiary md:table-cell">{groupLabelOf(data, m)}</td>
              <td className="px-3 py-1.5 text-right font-mono tabular-nums">{m.inDegree}</td>
              <td className="px-3 py-1.5 text-right font-mono tabular-nums">{m.outDegree}</td>
              <td className="hidden px-3 py-1.5 md:table-cell">{notes(m)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && <p className="py-10 text-center text-small text-text-secondary">Nothing matches.</p>}
      {rows.length > limit && (
        <div className="mt-4 flex items-center justify-center gap-3 text-[12px] text-text-tertiary">
          Showing {limit.toLocaleString("en-US")} of {rows.length.toLocaleString("en-US")}
          <button onClick={() => setLimit((l) => l + PAGE)} className="cs-chipbtn">
            Show {Math.min(PAGE, rows.length - limit)} more
          </button>
        </div>
      )}
    </div>
  );
}
