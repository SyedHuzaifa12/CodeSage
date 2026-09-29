/** One graph convention everywhere (Design System §6): every edge is observed; hotspots ringed; cycles red; orphans dashed. */
export function GraphLegend({ cycles, mode = "dependency" }: { cycles?: boolean; mode?: "dependency" | "call" }) {
  return (
    <div className="flex flex-wrap items-center gap-x-[18px] gap-y-1.5 font-mono text-[11px] text-text-tertiary">
      <span className="inline-flex items-center gap-1.5">
        <i className="inline-block h-[1.5px] w-[18px] bg-text-tertiary" aria-hidden="true" />
        observed {mode === "call" ? "call" : "dependency"}
      </span>
      {mode === "dependency" && (
        <>
          <span className="inline-flex items-center gap-1.5">
            <i className="inline-block h-2.5 w-2.5 rounded-full border-[1.5px] border-violet" aria-hidden="true" />
            hotspot
          </span>
          {cycles && (
            <span className="inline-flex items-center gap-1.5">
              <i className="inline-block h-[1.5px] w-[18px] bg-danger" aria-hidden="true" />
              cycle edge
            </span>
          )}
          <span className="inline-flex items-center gap-1.5">
            <i className="inline-block h-2.5 w-2.5 rounded-full border-[1.5px] border-dotted border-text-tertiary" aria-hidden="true" />
            orphan file
          </span>
        </>
      )}
    </div>
  );
}
