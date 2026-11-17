"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Settings } from "lucide-react";
import { NAV_ICONS } from "@/components/nav/NavRail";
import { cn } from "@/lib/utils";

/**
 * Mobile bottom nav: icon + label for the destinations that matter most on a small screen. Graph stays reachable
 * from Overview and the search palette.
 */
const MOBILE_ITEMS = [
  { label: "Overview", path: (id: string) => `/r/${id}` },
  { label: "Ask", path: (id: string) => `/r/${id}/ask` },
  { label: "Search", path: (id: string) => `/r/${id}/search` },
  { label: "Explorer", path: (id: string) => `/r/${id}/explorer` },
  { label: "Reports", path: (id: string) => `/r/${id}/reports` },
  { label: "Settings", path: (id: string) => `/r/${id}/settings` },
];

export function BottomNav({ repositoryId, ready }: { repositoryId: string; ready: boolean }) {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Repository sections"
      className="flex h-[58px] flex-shrink-0 items-stretch justify-around border-t border-border-subtle bg-[var(--cs-glass)] backdrop-blur-md"
    >
      {MOBILE_ITEMS.map((item) => {
        const href = item.path(repositoryId);
        const active = pathname === href || (item.label !== "Overview" && pathname?.startsWith(href));
        const disabled = !ready && item.label !== "Overview" && item.label !== "Settings";
        const Icon = item.label === "Settings" ? Settings : NAV_ICONS[item.label];
        return (
          <Link
            key={item.label}
            href={disabled ? "#" : href}
            aria-disabled={disabled || undefined}
            aria-current={active ? "page" : undefined}
            onClick={(e) => disabled && e.preventDefault()}
            className={cn(
              "flex min-w-0 flex-1 flex-col items-center justify-center gap-0.5 px-1 text-[10.5px] font-medium",
              disabled && "opacity-40",
              active ? "text-violet" : "text-text-tertiary",
            )}
          >
            {Icon && <Icon size={18} strokeWidth={1.7} aria-hidden="true" />}
            <span className="truncate">{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
