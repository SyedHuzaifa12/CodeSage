"use client";

import { AlertTriangle, Inbox, RefreshCw, Search, WifiOff } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";

/**
 * The rest of the system/data-state vocabulary (Design System §9.2):
 * Empty, Error, Partial, Stale, Offline. Every status pairs an icon with a
 * text label — never color alone (§12).
 */

export function EmptyState({
  message,
  action,
  icon,
  className,
}: {
  message: string;
  action?: { label: string; onClick: () => void };
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("cs-card flex flex-col items-center justify-center gap-2 p-8 text-center", className)}>
      <span className="text-text-tertiary" aria-hidden="true">
        {icon ?? <Inbox size={20} strokeWidth={1.6} />}
      </span>
      <span className="cs-mono-label normal-case tracking-normal">Empty</span>
      <p className="text-small text-text-secondary">{message}</p>
      {action && (
        <Button variant="primary" size="sm" onClick={action.onClick} className="mt-2">
          {action.label}
        </Button>
      )}
    </div>
  );
}

export function ErrorPanel({
  message,
  onRetry,
  className,
}: {
  message: string;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div className={cn("cs-card border-danger/35 p-4", className)} role="alert">
      <div className="mb-2 flex items-center gap-1.5">
        <AlertTriangle size={13} className="text-danger" aria-hidden="true" />
        <span className="cs-mono-label text-danger">Error</span>
      </div>
      <p className="text-small text-text-primary/90">{message}</p>
      {onRetry && (
        <button onClick={onRetry} className="mt-2 font-mono text-[10px] text-danger hover:underline">
          Retry &rarr;
        </button>
      )}
    </div>
  );
}

export function PartialNotice({ message, className }: { message: string; className?: string }) {
  return (
    <div className={cn("flex items-center gap-1.5 font-mono text-[10.5px] text-warning", className)} role="status">
      <AlertTriangle size={11} aria-hidden="true" />
      {message}
    </div>
  );
}

export function StaleBanner({
  message,
  onRegenerate,
  regenerating,
  className,
}: {
  message: string;
  onRegenerate?: () => void;
  regenerating?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center gap-3 font-mono text-[10.5px] text-warning", className)} role="status">
      <span className="flex items-center gap-1.5">
        <span className="h-1.5 w-1.5 rounded-full bg-warning" aria-hidden="true" />
        {message}
      </span>
      {onRegenerate && (
        <button onClick={onRegenerate} disabled={regenerating} className="inline-flex items-center gap-1 hover:underline disabled:opacity-50">
          <RefreshCw size={10} className={regenerating ? "animate-spin" : undefined} aria-hidden="true" />
          Regenerate
        </button>
      )}
    </div>
  );
}

export function OfflineBanner({ onRetry }: { onRetry: () => void }) {
  return (
    <div
      className="flex items-center justify-center gap-2 border-b border-danger/30 bg-danger/10 px-4 py-2 font-mono text-[11px] text-danger"
      role="alert"
    >
      <WifiOff size={13} aria-hidden="true" />
      Couldn&rsquo;t reach the CodeSage backend.
      <button onClick={onRetry} className="underline hover:no-underline">
        Retry
      </button>
    </div>
  );
}

export function NoResultsState({ query, className }: { query: string; className?: string }) {
  return (
    <div className={cn("flex flex-col items-center gap-2 py-16 text-center", className)}>
      <Search size={20} strokeWidth={1.6} className="text-text-tertiary" aria-hidden="true" />
      <p className="text-small text-text-secondary">No results for &ldquo;{query}&rdquo;.</p>
    </div>
  );
}

/** Cache/latency disclosure line (§9.3) — used ONLY inside already-opted-in detail surfaces. */
export function CacheDisclosureLine({ cacheHit, latencyMs }: { cacheHit: boolean; latencyMs: number }) {
  return (
    <span className="font-mono text-[10px] text-text-tertiary">
      cache &middot; {cacheHit ? `hit (${latencyMs}ms)` : `miss (${latencyMs}ms)`}
    </span>
  );
}
