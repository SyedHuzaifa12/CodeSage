"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAV_ITEMS, SETTINGS_PATH } from "@/lib/nav";
import { Tooltip } from "@/components/ui/Tooltip";
import { cn } from "@/lib/utils";

/**
 * Numbered index nav (Design System §16/§17) — desktop shows the full
 * "01 Overview" Newsreader-italic label; tablet collapses to bare numbers
 * (an intentional numbered-index gesture, not an icon-only fallback,
 * §16's "Responsive" section) with a hover tooltip carrying the label.
 */
export function NavRail({
  repositoryId,
  ready,
  variant = "desktop",
}: {
  repositoryId: string;
  ready: boolean;
  variant?: "desktop" | "tablet";
}) {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Repository sections"
      className={cn("flex flex-shrink-0 flex-col", variant === "desktop" ? "w-[150px] pt-6" : "w-11 items-center pt-5")}
    >
      {NAV_ITEMS.map((item) => {
        const href = item.path(repositoryId);
        const active = pathname === href || (item.num !== "01" && pathname?.startsWith(href));
        const disabled = !ready && !item.reachableBeforeReady;

        const link = (
          <Link
            key={item.num}
            href={disabled ? "#" : href}
            aria-current={active ? "page" : undefined}
            aria-disabled={disabled || undefined}
            tabIndex={disabled ? -1 : undefined}
            onClick={(e) => disabled && e.preventDefault()}
            className={cn(
              "flex items-baseline gap-2.5 py-[11px] transition-colors duration-standard ease-cs",
              variant === "tablet" && "flex-col items-center gap-0 py-2.5",
              disabled ? "cursor-not-allowed opacity-35" : "cursor-pointer",
              active ? "text-text-primary" : "text-[oklch(0.52_0.01_280)] hover:text-text-secondary",
            )}
          >
            <span
              className={cn(
                "font-mono text-[10.5px]",
                active ? "text-[oklch(0.82_0.13_300)]" : "text-[oklch(0.4_0.01_280)]",
              )}
            >
              {item.num}
            </span>
            {variant === "desktop" && <span className="font-display text-[14.5px] italic">{item.label}</span>}
          </Link>
        );

        return variant === "tablet" ? (
          <Tooltip key={item.num} label={disabled ? `${item.label} — indexing required` : item.label}>
            {link}
          </Tooltip>
        ) : (
          link
        );
      })}

      {variant === "desktop" && (
        <>
          <div className="flex-1" />
          <Link href={SETTINGS_PATH(repositoryId)} className="font-mono text-[10px] text-[oklch(0.4_0.01_280)] hover:text-text-secondary">
            settings
          </Link>
        </>
      )}
    </nav>
  );
}
