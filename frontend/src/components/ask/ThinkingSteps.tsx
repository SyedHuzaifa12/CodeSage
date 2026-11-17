"use client";

import { Check } from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

const STEPS = ["Searching the codebase", "Selecting the best evidence", "Writing the answer", "Checking it against the sources"];

/**
 * Shown while an answer is being produced: the stages the pipeline really goes through, with the current one
 * animated and an elapsed timer so a slow answer reads as progress, not a hang. (Stage timing is paced by the
 * client while the single request is in flight; see useAskStream.)
 */
export function ThinkingSteps({ stage, startedAt, onCancel }: { stage: number; startedAt: number; onCancel: () => void }) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const tick = () => setSeconds(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)));
    tick();
    const iv = setInterval(tick, 1000);
    return () => clearInterval(iv);
  }, [startedAt]);

  const current = Math.min(stage, STEPS.length - 1);
  return (
    <div role="status" aria-live="polite" className="cs-fade-in">
      <div className="flex items-center gap-2.5 text-[14px] font-medium text-text-primary">
        <span className="flex gap-1" aria-hidden="true">
          {[0, 1, 2].map((i) => (
            <span key={i} className="cs-pulse h-1.5 w-1.5 rounded-full bg-[var(--cs-accent-violet)]" style={{ animationDelay: `${i * 160}ms` }} />
          ))}
        </span>
        {STEPS[current]}…
        <span className="cs-tabular text-[12.5px] font-normal text-text-tertiary">{seconds}s</span>
      </div>
      <ol className="mt-3 grid list-none gap-1.5 p-0">
        {STEPS.map((label, i) => {
          const done = i < current;
          const active = i === current;
          return (
            <li key={label} className={cn("flex items-center gap-2.5 text-[13px] transition-colors", done ? "text-text-secondary" : active ? "text-text-primary" : "text-text-tertiary opacity-60")}>
              <span
                className={cn(
                  "grid h-4 w-4 flex-none place-items-center rounded-full border",
                  done ? "border-transparent bg-[var(--cs-success)] text-white" : active ? "border-[var(--cs-accent-violet)]" : "border-border-strong",
                )}
                aria-hidden="true"
              >
                {done ? <Check size={10} strokeWidth={3} /> : active ? <span className="cs-pulse h-1.5 w-1.5 rounded-full bg-[var(--cs-accent-violet)]" /> : null}
              </span>
              {label}
            </li>
          );
        })}
      </ol>
      <button type="button" onClick={onCancel} className="mt-3 text-[12.5px] font-medium text-text-tertiary underline-offset-2 hover:text-text-primary hover:underline">
        Stop
      </button>
    </div>
  );
}
