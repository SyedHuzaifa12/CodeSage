"use client";

import { TopologyMark } from "@/components/devices/TopologyMark";
import { OnboardingProgressRow } from "@/components/domain/OnboardingProgressRow";
import { Button } from "@/components/ui/Button";
import { ErrorPanel } from "@/components/state/StateVocabulary";
import { useTriggerIndex } from "@/lib/query/workspace";
import type { Repository } from "@/lib/types/repository";

/**
 * Onboarding/indexing narrative (Design System §4/§10/§16/§17), rendered
 * directly on Overview — not a separate wizard.
 *
 * IMPORTANT, discovered while reading the real pipeline
 * (backend/app/ingestion/parsing_service.py::run_parsing_pipeline): parse
 * -> intelligence -> knowledge/embedding all run in ONE background task on
 * ONE uncommitted SQLAlchemy session, committed only once at the very end.
 * Per-file `indexing_progress` writes are flushed, not committed, so a
 * concurrent polling request on a different connection cannot observe
 * incremental progress — indexing_status/progress will appear to sit still
 * and then jump straight to "indexed" when the whole chain finishes. This
 * is a genuine backend limitation, not a frontend bug: the UI below shows
 * one honest indeterminate "Building understanding" step for the whole
 * parse+relationships+semantic-index phase rather than fabricating a
 * granular percentage the backend cannot actually report yet.
 */
export function OnboardingNarrative({ repository }: { repository: Repository }) {
  const triggerIndex = useTriggerIndex();
  const failed = repository.status === "failed" || repository.indexing_status === "failed";

  const cloned = repository.status === "ready" || repository.status === "cloning" ? repository.status === "ready" : false;
  const indexingActive = repository.indexing_status === "indexing";
  const indexed = repository.indexing_status === "indexed";

  return (
    <div className="relative flex min-h-[70vh] items-center justify-center gap-20 overflow-hidden px-8 py-12">
      <TopologyMark variant="watermark" />
      <div className="relative z-10 flex w-full max-w-[520px] flex-col gap-8">
        <div>
          <div className="cs-mono-label mb-2.5">UNDERSTANDING A REPOSITORY</div>
          <h1 className="font-display text-masthead italic text-text-primary">{repository.name}</h1>
          {repository.github_url && (
            <div className="mt-2 font-mono text-[11px] text-text-tertiary">{repository.github_url}</div>
          )}
        </div>

        <div className="flex flex-col">
          <OnboardingProgressRow
            state={repository.status === "pending" ? "active" : cloned ? "done" : "pending"}
            title="Cloning repository"
            detail={repository.status === "cloning" ? "Fetching files…" : undefined}
          />
          <OnboardingProgressRow
            state={indexed ? "done" : indexingActive ? "active" : "pending"}
            title="Building understanding"
            detail="Parsing symbols, mapping relationships, building the semantic index"
            progressFraction={indexingActive ? 0.5 : undefined}
          />
          <OnboardingProgressRow state={indexed ? "done" : "pending"} title="Ready for Ask, Search, Graph and Reports" />
        </div>

        {failed && (
          <ErrorPanel
            message={repository.error_message ?? "Something went wrong while processing this repository."}
            onRetry={() => triggerIndex.mutate(repository.id)}
          />
        )}

        {repository.status === "ready" && repository.indexing_status === "not_started" && (
          <Button variant="primary" onClick={() => triggerIndex.mutate(repository.id)} loading={triggerIndex.isPending}>
            Start indexing
          </Button>
        )}

        <div className="font-mono text-[10.5px] text-text-tertiary">
          Overview and Explorer are viewable now &middot; Ask, Search, Graph and Reports unlock when indexing finishes
        </div>
      </div>
    </div>
  );
}
