"use client";

import { Compass, FlaskConical, MessageSquareText, Network, Settings2, ShieldCheck, Zap, FileSearch, type LucideIcon } from "lucide-react";
import { TopologyMark } from "@/components/devices/TopologyMark";

function iconFor(question: string): LucideIcon {
  const q = question.toLowerCase();
  if (q.includes("architecture") || q.includes("structured")) return Compass;
  if (q.includes("depend")) return Network;
  if (q.includes("affected") || q.includes("change")) return Zap;
  if (q.includes("test")) return FlaskConical;
  if (q.includes("config")) return Settings2;
  return MessageSquareText;
}

/** What the user sees before their first question: what this is, what to try, and why the answers can be trusted. */
export function EmptyChat({
  repositoryName,
  symbolCount,
  suggestions,
  onPick,
}: {
  repositoryName?: string;
  symbolCount?: number;
  suggestions: string[];
  onPick: (question: string) => void;
}) {
  return (
    <div className="mx-auto flex max-w-[720px] flex-col items-center pb-6 pt-10 text-center sm:pt-16">
      <span className="grid h-14 w-14 place-items-center rounded-[18px] border border-border-subtle bg-surface-1 shadow-sm">
        <TopologyMark variant="mark" size={30} />
      </span>
      <h1 className="mt-5 text-[26px] font-semibold tracking-tight text-text-primary sm:text-[30px]">
        {repositoryName ? `Ask about ${repositoryName}` : "Ask about this repository"}
      </h1>
      <p className="mt-2 max-w-[56ch] text-[15px] leading-relaxed text-text-secondary">
        Get answers grounded in the repository&rsquo;s real code, with citations to the exact files and lines
        {symbolCount ? ` — drawing on ${symbolCount.toLocaleString("en-US")} indexed symbols` : ""}.
      </p>

      <div className="mt-8 grid w-full gap-2.5 text-left sm:grid-cols-2">
        {suggestions.slice(0, 4).map((s) => {
          const Icon = iconFor(s);
          return (
            <button
              key={s}
              type="button"
              onClick={() => onPick(s)}
              className="group flex items-start gap-3 rounded-[12px] border border-border-strong bg-surface-1 p-3.5 text-left shadow-sm transition-[border-color,background,transform] hover:border-[var(--cs-violet-line)] hover:bg-surface-2 active:scale-[0.99]"
            >
              <span className="mt-0.5 grid h-7 w-7 flex-none place-items-center rounded-[8px] bg-[var(--cs-violet-tint)] text-violet">
                <Icon size={15} strokeWidth={1.8} aria-hidden="true" />
              </span>
              <span className="text-[14px] font-medium leading-snug text-text-primary">{s}</span>
            </button>
          );
        })}
      </div>

      <ul className="mt-8 flex flex-wrap justify-center gap-x-6 gap-y-2 text-[12.5px] text-text-tertiary">
        <li className="inline-flex items-center gap-1.5">
          <FileSearch size={14} aria-hidden="true" /> Cites exact files and lines
        </li>
        <li className="inline-flex items-center gap-1.5">
          <ShieldCheck size={14} aria-hidden="true" /> Checked against the evidence
        </li>
      </ul>
    </div>
  );
}
