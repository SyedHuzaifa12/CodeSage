"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

/**
 * Mobile bottom nav (Design System §11/§16): a quiet mono label bar, not
 * icon buttons — the four highest-value destinations on a small screen
 * (Overview, Ask, Search, Reports); Explorer/Graph/Settings stay reachable
 * from Overview on mobile rather than crowding the bar.
 */
const MOBILE_ITEMS = [
  { label: "overview", path: (id: string) => `/r/${id}` },
  { label: "ask", path: (id: string) => `/r/${id}/ask` },
  { label: "search", path: (id: string) => `/r/${id}/search` },
  { label: "reports", path: (id: string) => `/r/${id}/reports` },
];

export function BottomNav({ repositoryId, ready }: { repositoryId: string; ready: boolean }) {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Repository sections"
      className="flex h-[52px] flex-shrink-0 items-center justify-around border-t border-border-subtle font-mono text-[9.5px]"
    >
      {MOBILE_ITEMS.map((item) => {
        const href = item.path(repositoryId);
        const active = pathname === href || (item.label !== "overview" && pathname?.startsWith(href));
        const disabled = !ready && item.label !== "overview";
        return (
          <Link
            key={item.label}
            href={disabled ? "#" : href}
            aria-disabled={disabled || undefined}
            onClick={(e) => disabled && e.preventDefault()}
            className={cn(
              "px-2 py-1",
              disabled && "opacity-35",
              active ? "border-b-[1.5px] border-violet text-violet" : "text-text-tertiary",
            )}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
