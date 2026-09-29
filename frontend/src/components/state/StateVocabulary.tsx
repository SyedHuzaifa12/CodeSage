"use client";

import { AlertTriangle, Info, RefreshCw, Search, WifiOff } from "lucide-react";
import type { ReactNode } from "react";
import { TopologyMark } from "@/components/devices/TopologyMark";
import { Button } from "@/components/ui/Button";
import { ApiError } from "@/lib/api/client";
import { cn } from "@/lib/utils";

/**
 * System-state vocabulary (Design System §9.2) — implemented once, reused
 * everywhere data loads. Boxless by default: rules and whitespace compose
 * the page; tinted notices are reserved for genuine state changes.
 */

export function EmptyState({
  message,
  action,
  icon,
  detail,
  className,
}: {
  message: string;
  action?: { label: string; onClick: () => void };
  icon?: ReactNode;
  detail?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-start gap-3 py-8", className)}>
      <span className="text-text-tertiary" aria-hidden="true">
        {icon ?? <TopologyMark variant="mark" size={26} />}
      </span>
      <p className="cs-lede !text-[17px]">{message}</p>
      {detail && <div className="text-small text-text-secondary">{detail}</div>}
      {action && (
        <Button variant="primary" onClick={action.onClick} className="mt-1">
          {action.label}
        </Button>
      )}
    </div>
  );
}

export type NoticeTone = "info" | "warn" | "bad";

export function Notice({
  tone = "info",
  title,
  children,
  actions,
  className,
  role,
}: {
  tone?: NoticeTone;
  title?: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
  className?: string;
  role?: "alert" | "status";
}) {
  const Icon = tone === "bad" ? AlertTriangle : tone === "warn" ? AlertTriangle : Info;
  const color = tone === "bad" ? "text-danger" : tone === "warn" ? "text-warning" : "text-info";
  return (
    <div
      className={cn("cs-notice", tone === "bad" ? "cs-notice-bad" : tone === "warn" ? "cs-notice-warn" : "cs-notice-info", className)}
      role={role ?? (tone === "bad" ? "alert" : "status")}
    >
      <Icon size={16} strokeWidth={1.6} className={cn("mt-0.5 flex-none", color)} aria-hidden="true" />
      <div className="min-w-0 flex-1">
        {title && <b>{title}</b>}
        {children && <div className={cn(title && "mt-0.5", "text-text-secondary")}>{children}</div>}
        {actions && <div className="mt-2.5 flex flex-wrap gap-2">{actions}</div>}
      </div>
    </div>
  );
}

/** Error panel: a human headline, the backend's own message, and a Retry action. */
export function ErrorPanel({
  message,
  error,
  onRetry,
  title,
  className,
}: {
  message?: string;
  error?: unknown;
  onRetry?: () => void;
  title?: string;
  className?: string;
}) {
  const api = error instanceof ApiError ? error : null;
  const headline =
    title ??
    (api?.kind === "network"
      ? "Can't reach the CodeSage backend"
      : api?.kind === "timeout"
        ? "The request timed out"
        : api?.status === 409
          ? "Not ready yet"
          : "The request failed");
  const detail = message ?? (error instanceof Error ? error.message : undefined);
  return (
    <Notice
      tone="bad"
      title={headline}
      className={className}
      actions={
        onRetry && (
          <Button size="sm" variant="secondary" onClick={onRetry}>
            <RefreshCw size={13} aria-hidden="true" />
            Retry
          </Button>
        )
      }
    >
      {detail && (
        <div className="cs-errmono">
          {api?.status ? `HTTP ${api.status} · ` : ""}
          {detail}
        </div>
      )}
    </Notice>
  );
}

export function PartialNotice({ message, className }: { message: string; className?: string }) {
  return (
    <Notice tone="info" className={className}>
      {message}
    </Notice>
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
    <Notice
      tone="warn"
      title="Re-indexed since generation"
      className={className}
      actions={
        onRegenerate && (
          <Button size="sm" variant="secondary" onClick={onRegenerate} loading={regenerating}>
            {!regenerating && <RefreshCw size={13} aria-hidden="true" />}
            Regenerate
          </Button>
        )
      }
    >
      {message}
    </Notice>
  );
}

export function OfflineBanner({ onRetry, retryInSeconds }: { onRetry: () => void; retryInSeconds?: number }) {
  return (
    <div
      className="flex flex-wrap items-center justify-center gap-x-3.5 gap-y-1 border-b border-danger/30 bg-danger/10 px-5 py-2 text-[13px]"
      role="alert"
    >
      <WifiOff size={15} className="text-danger" aria-hidden="true" />
      <span>
        <b className="font-semibold">Can&rsquo;t reach the CodeSage backend</b>
        <span className="text-text-secondary">
          {" "}
          — GET /health failed{retryInSeconds !== undefined ? `. Retrying in ${retryInSeconds}s` : ""}.
        </span>
      </span>
      <Button size="sm" variant="secondary" onClick={onRetry}>
        Retry now
      </Button>
    </div>
  );
}

export function NoResultsState({ query, hint, className }: { query: string; hint?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col items-start gap-2 py-10", className)}>
      <Search size={18} strokeWidth={1.6} className="text-text-tertiary" aria-hidden="true" />
      <p className="cs-lede !text-[18px]">No matching results for &ldquo;{query}&rdquo;.</p>
      {hint && <div className="max-w-[62ch] text-small text-text-secondary">{hint}</div>}
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
