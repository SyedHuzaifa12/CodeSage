"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowLeft, Settings } from "lucide-react";
import { NAV_ITEMS, SETTINGS_PATH } from "@/lib/nav";
import { Tooltip } from "@/components/ui/Tooltip";
import { cn } from "@/lib/utils";

/**
 * Numbered index nav (Design System §16/§17). Desktop shows the full
 * "01 Overview" Newsreader-italic label; tablet collapses to bare numbers.
 * Gated items carry a tooltip at every breakpoint.
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
  const desktop = variant === "desktop";
  const settingsHref = SETTINGS_PATH(repositoryId);
  return (
    <nav
      aria-label="Repository sections"
      className={cn(
        "flex flex-shrink-0 flex-col overflow-y-auto border-r border-border-subtle bg-[linear-gradient(180deg,oklch(0.162_0.007_280),var(--cs-bg)_70%)] pb-4 pt-6",
        desktop ? "w-[176px]" : "w-16",
      )}
    >
      {NAV_ITEMS.map((item) => {
        const href = item.path(repositoryId);
        const active = pathname === href || (item.num !== "01" && pathname?.startsWith(href));
        const disabled = !ready && !item.reachableBeforeReady;
        const inner = (
          <span className={cn("flex items-baseline gap-3", !desktop && "justify-center")}>
            <span className={cn("w-[18px] flex-none font-mono text-[11px]", !desktop && "w-auto text-[12px]", active ? "text-violet" : "text-text-tertiary")}>
              {item.num}
            </span>
            {desktop && <span className="font-display text-[16.5px] italic leading-tight">{item.label}</span>}
          </span>
        );
        const className = cn(
          "relative mx-2.5 my-px block rounded-[7px] py-[9px] transition-[color,background] duration-standard ease-cs",
          desktop ? "pl-3" : "px-0",
          disabled
            ? "cursor-not-allowed text-text-secondary opacity-35"
            : active
              ? "bg-[linear-gradient(90deg,var(--cs-violet-tint),transparent_85%)] text-text-primary before:absolute before:-left-2.5 before:bottom-[7px] before:top-[7px] before:w-[2px] before:bg-violet"
              : "text-text-secondary hover:bg-white/[0.025] hover:text-text-primary",
        );
        const tip = disabled ? `${item.label} — indexing required` : !desktop ? item.label : null;
        const el = disabled ? (
          <span key={item.num} className={className} aria-disabled="true" tabIndex={0} aria-label={`${item.label} (indexing required)`}>
            {inner}
          </span>
        ) : (
          <Link key={item.num} href={href} aria-current={active ? "page" : undefined} className={className} aria-label={desktop ? undefined : item.label}>
            {inner}
          </Link>
        );
        return tip ? (
          <Tooltip key={item.num} label={tip}>
            {el}
          </Tooltip>
        ) : (
          el
        );
      })}
      <div className="min-h-5 flex-1" />
      <div className={cn("flex flex-col border-t border-border-subtle pt-2.5", desktop ? "mx-4" : "mx-1.5")}>
        {[
          { href: settingsHref, label: "settings", icon: <Settings size={13} aria-hidden="true" />, active: pathname === settingsHref },
          { href: "/", label: "repositories", icon: <ArrowLeft size={13} aria-hidden="true" />, active: false },
        ].map((l) => {
          const link = (
            <Link
              key={l.label}
              href={l.href}
              aria-current={l.active ? "page" : undefined}
              aria-label={desktop ? undefined : l.label}
              className={cn(
                "flex items-center gap-2 rounded px-1.5 py-[7px] font-mono text-[11px] tracking-[0.06em] hover:text-text-primary",
                l.active ? "text-text-primary" : "text-text-tertiary",
                !desktop && "justify-center",
              )}
            >
              {l.icon}
              {desktop && l.label}
            </Link>
          );
          return desktop ? link : (
            <Tooltip key={l.label} label={l.label}>
              {link}
            </Tooltip>
          );
        })}
      </div>
    </nav>
  );
}
