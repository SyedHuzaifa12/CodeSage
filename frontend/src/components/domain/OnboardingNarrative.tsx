"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowRight, Check, X } from "lucide-react";
import { TopologyMark } from "@/components/devices/TopologyMark";
import { DeleteRepositoryDialog } from "@/components/domain/DeleteRepositoryDialog";
import { Button } from "@/components/ui/Button";
import { ErrorPanel, Notice } from "@/components/state/StateVocabulary";
import { useTriggerIndex, useWorkspace } from "@/lib/query/workspace";
import type { Repository } from "@/lib/types/repository";
import { cn, formatNumber } from "@/lib/utils";

/** Long enough that a small repository has certainly finished; after this a stuck task is plausible. */
const SLOW_AFTER_MS = 4 * 60_000;

function formatBytes(b: number): string {
  if (b >= 1e6) return `${(b / 1e6).toFixed(1)} MB`;
  if (b >= 1e3) return `${(b / 1e3).toFixed(1)} KB`;
  return `${b} B`;
}

type StepState = "done" | "active" | "pending" | "failed";

function Step({ state, title, detail, children }: { state: StepState; title: string; detail: string; children?: React.ReactNode }) {
  return (
    <div
      role="listitem"
      className={cn(
        "grid grid-cols-[28px_1fr] gap-3.5 border-t border-border-subtle py-[18px] last:border-b",
        state === "active" && "bg-[linear-gradient(90deg,oklch(0.75_0.13_300/0.05),transparent_80%)]",
        state === "pending" && "opacity-55",
      )}
    >
      <span
        className={cn(
          "mt-0.5 grid h-[18px] w-[18px] place-items-center rounded-full border-[1.5px] border-border-strong",
          state === "done" && "border-success bg-success text-bg",
          state === "active" && "border-violet shadow-[0_0_0_4px_var(--cs-violet-tint)]",
          state === "failed" && "border-danger text-danger",
        )}
        aria-hidden="true"
      >
        {state === "done" && <Check size={11} strokeWidth={3} />}
        {state === "failed" && <X size={11} strokeWidth={3} />}
        {state === "active" && <span className="cs-pulse h-1.5 w-1.5 rounded-full bg-violet" />}
      </span>
      <div className="min-w-0">
        <div className="text-[14.5px] font-semibold text-text-primary">{title}</div>
        <div className="mt-0.5 text-[13px] text-text-secondary">{detail}</div>
        {children}
      </div>
    </div>
  );
}

/**
 * Onboarding/indexing narrative (Design System §4), rendered on Overview.
 *
 * The backend runs parse -> intelligence -> knowledge in ONE background
 * task committed once at the end, so no intermediate progress is
 * observable: this shows one honest indeterminate step and an elapsed
 * timer, never a fabricated percentage.
 */
export function OnboardingNarrative({ repository }: { repository: Repository }) {
  const router = useRouter();
  const trigger = useTriggerIndex();
  const cloned = repository.status === "ready";
  const cloneFailed = repository.status === "failed";
  const indexing = repository.indexing_status === "indexing";
  const indexFailed = repository.indexing_status === "failed";
  const indexed = repository.indexing_status === "indexed";
  const workspace = useWorkspace(cloned ? repository.id : undefined);
  const [startedAt] = useState(() => Date.now());
  const [now, setNow] = useState(Date.now());
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (!indexing) return;
    const iv = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(iv);
  }, [indexing]);

  const elapsed = Math.max(0, Math.round((now - startedAt) / 1000));
  const ws = workspace.data;

  return (
    <div className="cs-page cs-page-glow">
      <TopologyMark variant="watermark" />
      <div className="relative z-10 mx-auto max-w-[600px] px-5 pb-24 pt-12 sm:px-7 sm:pt-14">
        <p className="cs-mono-label">Understanding a repository</p>
        <h1 className="cs-masthead mt-2">{repository.name}</h1>
        {repository.github_url && <p className="cs-monoline mt-2">{repository.github_url}</p>}
        {ws && (
          <div className="mt-4 flex flex-wrap gap-x-5 gap-y-1 font-mono text-[12px] text-text-secondary">
            <span><b className="font-medium text-text-primary">{formatNumber(ws.total_files)}</b> files scanned</span>
            <span><b className="font-medium text-text-primary">{Object.keys(ws.language_distribution).length}</b> languages</span>
            <span><b className="font-medium text-text-primary">{ws.folder_count}</b> folders</span>
            <span>{formatBytes(ws.repository_size_bytes)}</span>
          </div>
        )}

        <div role="list" className="mt-9">
          <Step
            state={cloneFailed ? "failed" : cloned ? "done" : "active"}
            title="Cloning repository"
            detail={cloneFailed ? "The clone failed." : cloned ? "Shallow clone of the default branch, then a file scan." : "Fetching files…"}
          />
          <Step
            state={indexed ? "done" : indexFailed ? "failed" : indexing ? "active" : "pending"}
            title="Building understanding"
            detail="Parsing symbols, mapping relationships, building the semantic index"
          >
            {indexing && (
              <>
                <div className="cs-indet mt-3" role="progressbar" aria-label="Indexing in progress" aria-valuetext="In progress" />
                <div className="mt-2 flex flex-wrap gap-x-2 text-[12px] text-text-tertiary">
                  <span className="cs-tabular font-mono">
                    watching {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, "0")}
                  </span>
                  <span>· the backend reports only start and finish</span>
                </div>
              </>
            )}
          </Step>
          <Step
            state={indexed ? "done" : "pending"}
            title="Ready for Ask, Search, Graph and Reports"
            detail={indexed ? "Composing the overview…" : "Unlocks when indexing finishes."}
          />
        </div>

        {indexing && now - startedAt > SLOW_AFTER_MS && (
          <Notice tone="warn" title="Taking longer than expected" className="mt-6">
            Large repositories can take several minutes. If the background task crashed, the repository stays in INDEXING — there is no
            cancel endpoint yet, so check the backend logs.
          </Notice>
        )}

        {cloned && repository.indexing_status === "not_started" && (
          <div className="mt-8">
            <Button variant="primary" onClick={() => trigger.mutate(repository.id)} loading={trigger.isPending}>
              {!trigger.isPending && <ArrowRight size={15} aria-hidden="true" />}
              Start indexing
            </Button>
            <p className="mt-3 text-small text-text-tertiary">
              Runs one background task: Tree-sitter parse (Python, JavaScript, TypeScript, Java) → repository intelligence → chunking and local
              embeddings.
            </p>
            {trigger.isError && <ErrorPanel className="mt-3" error={trigger.error} />}
          </div>
        )}

        {cloneFailed && (
          <Notice
            tone="bad"
            title="Clone failed"
            className="mt-6"
            actions={
              <Button size="sm" variant="secondary" onClick={() => setDeleting(true)}>
                Delete &amp; re-add
              </Button>
            }
          >
            {repository.error_message && <div className="cs-errmono">{repository.error_message}</div>}
            <p className="mt-2 text-small">There is no re-clone endpoint. Delete this entry and add the repository again once it&rsquo;s reachable.</p>
          </Notice>
        )}

        {indexFailed && cloned && (
          <Notice
            tone="bad"
            title="Indexing failed"
            className="mt-6"
            actions={
              <Button size="sm" variant="secondary" onClick={() => trigger.mutate(repository.id)} loading={trigger.isPending}>
                Retry indexing
              </Button>
            }
          >
            {repository.error_message && <div className="cs-errmono">{repository.error_message}</div>}
          </Notice>
        )}

        <p className="cs-monoline mt-9">Overview and Explorer are viewable now · Ask, Search, Graph and Reports unlock when indexing finishes</p>
        {cloned && (
          <Link href={`/r/${repository.id}/explorer`} className="cs-link mt-3">
            Browse the file tree <ArrowRight size={13} aria-hidden="true" />
          </Link>
        )}
      </div>
      <DeleteRepositoryDialog repository={deleting ? repository : null} onClose={() => setDeleting(false)} onDeleted={() => router.push("/")} />
    </div>
  );
}
