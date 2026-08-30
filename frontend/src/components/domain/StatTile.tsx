import { cn } from "@/lib/utils";

/**
 * A hero stat, not four equal stats (Design System §15/§16): the plain
 * quiet inline mono strip for demoted/supporting numbers, plus a hero
 * variant reserved for the one number the page wants to foreground. Which
 * stat is "hero" is a per-page config decision (§15 trade-offs), never
 * hardcoded into this component.
 */
export function InlineStat({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <div className={cn("flex items-baseline gap-1.5", className)}>
      <span className="font-mono text-[9.5px] text-text-tertiary">{label}</span>
      <span className="font-mono text-[12px] text-text-secondary">{value}</span>
    </div>
  );
}

export function HeroStat({
  label,
  value,
  caption,
  progressFraction,
  className,
}: {
  label: string;
  value: string;
  caption?: string;
  progressFraction?: number;
  className?: string;
}) {
  return (
    <div className={cn("cs-card border-violet/20 p-4", className)}>
      <div className="cs-mono-label text-[oklch(0.82_0.1_300)]">{label}</div>
      <div className="mt-1 font-display text-[32px] text-text-primary">{value}</div>
      {caption && <div className="mt-1 text-[11px] text-text-secondary">{caption}</div>}
      {progressFraction !== undefined && (
        <div className="mt-2 h-[3px] overflow-hidden rounded-full bg-white/[0.08]">
          <div
            className="h-full rounded-full"
            style={{
              width: `${Math.min(100, Math.max(0, progressFraction * 100))}%`,
              background: "linear-gradient(90deg, oklch(0.65 0.1 300), oklch(0.85 0.13 300))",
            }}
          />
        </div>
      )}
    </div>
  );
}
