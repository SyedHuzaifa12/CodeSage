"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowLeft, FileText, FolderTree, LayoutDashboard, MessageSquareText, Network, Search, Settings, type LucideIcon } from "lucide-react";
import { NAV_ITEMS, SETTINGS_PATH } from "@/lib/nav";
import { Tooltip } from "@/components/ui/Tooltip";
import { cn } from "@/lib/utils";

/** One icon per section, shared with the mobile bar so a section looks the same everywhere. */
export const NAV_ICONS: Record<string, LucideIcon> = {
  Overview: LayoutDashboard,
  Ask: MessageSquareText,
  Explorer: FolderTree,
  Search,
  Graph: Network,
  Reports: FileText,
};

/**
 * Repository section navigation: an icon and a plain label per section. Desktop shows labels; tablet collapses to
 * icons with tooltips. Sections that need a finished index are dimmed and say so in a tooltip.
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
        "flex flex-shrink-0 flex-col overflow-y-auto border-r border-border-subtle bg-surface-1 pb-4 pt-4",
        desktop ? "w-[212px]" : "w-16",
      )}
    >
      <div className="flex flex-col gap-0.5 px-2.5">
        {NAV_ITEMS.map((item) => {
          const href = item.path(repositoryId);
          const active = pathname === href || (item.num !== "01" && pathname?.startsWith(href));
          const disabled = !ready && !item.reachableBeforeReady;
          const Icon = NAV_ICONS[item.label];
          const inner = (
            <>
              {Icon && <Icon size={17} strokeWidth={1.7} className="flex-none" aria-hidden="true" />}
              {desktop && <span className="truncate">{item.label}</span>}
            </>
          );
          const className = cn(
            "flex items-center gap-3 rounded-[8px] px-3 py-2 text-[14px] font-medium transition-colors duration-micro ease-cs",
            !desktop && "justify-center px-0",
            disabled
              ? "cursor-not-allowed text-text-secondary opacity-45"
              : active
                ? "bg-[var(--cs-violet-tint)] text-violet"
                : "text-text-secondary hover:bg-surface-2 hover:text-text-primary",
          );
          const tip = disabled ? `${item.label} — available once indexing finishes` : !desktop ? item.label : null;
          const el = disabled ? (
            <span key={item.num} className={className} aria-disabled="true" tabIndex={0} aria-label={`${item.label} (available once indexing finishes)`}>
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
      </div>
      <div className="min-h-5 flex-1" />
      <div className="mx-2.5 flex flex-col gap-0.5 border-t border-border-subtle pt-3">
        {[
          { href: settingsHref, label: "Settings", icon: <Settings size={16} strokeWidth={1.7} aria-hidden="true" />, active: pathname === settingsHref },
          { href: "/", label: "All repositories", icon: <ArrowLeft size={16} strokeWidth={1.7} aria-hidden="true" />, active: false },
        ].map((l) => {
          const link = (
            <Link
              key={l.label}
              href={l.href}
              aria-current={l.active ? "page" : undefined}
              aria-label={desktop ? undefined : l.label}
              className={cn(
                "flex items-center gap-3 rounded-[8px] px-3 py-2 text-[13.5px] font-medium transition-colors hover:bg-surface-2 hover:text-text-primary",
                l.active ? "bg-[var(--cs-violet-tint)] text-violet" : "text-text-secondary",
                !desktop && "justify-center px-0",
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
