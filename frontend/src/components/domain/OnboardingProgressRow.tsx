"use client";

import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

export type OnboardingRowState = "done" | "active" | "pending";

/**
 * Onboarding progress row (Design System §4/§16/§17): a plain vertical
 * sequence separated by hairlines. The active step's ring is a
 * partial-arc SVG progress indicator around its dot, not a plain circle.
 */
export function OnboardingProgressRow({
  state,
  title,
  detail,
  progressFraction,
}: {
  state: OnboardingRowState;
  title: string;
  detail?: string;
  progressFraction?: number;
}) {
  return (
    <div
      className={cn(
        "flex items-start gap-[18px] border-b border-border-subtle py-[15px] last:border-b-0",
        state === "pending" && "opacity-35",
      )}
    >
      <span className="mt-0.5 flex h-[15px] w-[15px] flex-shrink-0 items-center justify-center">
        {state === "done" && <Check size={15} strokeWidth={2.6} className="text-success" aria-hidden="true" />}
        {state === "active" && (
          <svg width={15} height={15} viewBox="0 0 15 15" aria-hidden="true">
            <circle cx={7.5} cy={7.5} r={6.5} fill="none" stroke="oklch(0.75 0.13 300 / 0.18)" strokeWidth={1.6} />
            <circle
              cx={7.5}
              cy={7.5}
              r={6.5}
              fill="none"
              stroke="oklch(0.82 0.13 300)"
              strokeWidth={1.6}
              strokeDasharray={40.8}
              strokeDashoffset={40.8 * (1 - (progressFraction ?? 0.5))}
              strokeLinecap="round"
              transform="rotate(-90 7.5 7.5)"
            />
          </svg>
        )}
        {state === "pending" && (
          <span className="block h-[15px] w-[15px] rounded-full border-[1.5px] border-text-tertiary" aria-hidden="true" />
        )}
      </span>
      <div className="flex-1">
        <div className={cn("text-[14px]", state === "active" ? "text-text-primary" : "text-text-primary/90")}>
          {title}
        </div>
        {detail && <div className="mt-0.5 font-mono text-[10.5px] text-text-tertiary">{detail}</div>}
        {state === "active" && progressFraction !== undefined && (
          <>
            <div className="mt-2.5 h-[2px] overflow-hidden bg-white/[0.08]">
              <div
                className="h-full"
                style={{
                  width: `${progressFraction * 100}%`,
                  background: "linear-gradient(90deg, oklch(0.65 0.1 300), oklch(0.85 0.13 300))",
                }}
              />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
