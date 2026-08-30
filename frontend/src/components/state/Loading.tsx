import { cn } from "@/lib/utils";

/**
 * System-state vocabulary — Loading (Design System §9.2): skeleton shapes
 * matching the real layout's geometry, never a generic spinner for
 * anything that takes >300ms.
 */
export function SkeletonLine({ width = "100%", className }: { width?: string; className?: string }) {
  return <div className={cn("cs-skel h-[11px]", className)} style={{ width }} />;
}

export function SkeletonBlock({ className }: { className?: string }) {
  return (
    <div className={cn("cs-card flex flex-col gap-2 p-4", className)}>
      <SkeletonLine width="70%" />
      <SkeletonLine width="90%" />
      <SkeletonLine width="55%" />
    </div>
  );
}

/** Reserved for sub-300ms, position-fixed actions (button pending state) only. */
export function Spinner({ size = 14, className }: { size?: number; className?: string }) {
  return (
    <span
      className={cn("inline-block animate-spin rounded-full border-2 border-current border-t-transparent", className)}
      style={{ width: size, height: size }}
      aria-hidden="true"
    />
  );
}
