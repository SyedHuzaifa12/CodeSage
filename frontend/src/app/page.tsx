"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Trash2 } from "lucide-react";
import { TopologyMark } from "@/components/devices/TopologyMark";
import { RepoStatusChip } from "@/components/domain/RepoStatusChip";
import { Button } from "@/components/ui/Button";
import { BoxedInput } from "@/components/ui/Input";
import { EmptyState, ErrorPanel } from "@/components/state/StateVocabulary";
import { SkeletonLine } from "@/components/state/Loading";
import { Modal } from "@/components/ui/Modal";
import { useCreateRepository, useDeleteRepository, useRepositories } from "@/lib/query/repositories";
import { ApiError } from "@/lib/api/client";
import { formatRelativeTime } from "@/lib/utils";

/**
 * Repositories — workspace home (Design System §1). No canvas mockup
 * exists for this screen (the approved artboards start once a repository
 * is selected); composed here from the same tokens/typography/masthead
 * pattern used everywhere else, deliberately not a new visual language.
 */
export default function RepositoriesPage() {
  const { data, isLoading, isError, error, refetch } = useRepositories();
  const createMutation = useCreateRepository();
  const deleteMutation = useDeleteRepository();
  const [githubUrl, setGithubUrl] = useState("");
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [confirmText, setConfirmText] = useState("");

  const repositories = data?.repositories ?? [];
  const pendingDelete = repositories.find((r) => r.id === pendingDeleteId);

  function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (!githubUrl.trim()) return;
    createMutation.mutate(
      { github_url: githubUrl.trim() },
      { onSuccess: () => setGithubUrl("") },
    );
  }

  return (
    <div className="relative min-h-screen overflow-hidden">
      <TopologyMark variant="watermark" />
      <div className="relative z-10 mx-auto flex max-w-[860px] flex-col gap-10 px-8 py-16">
        <header className="flex items-center gap-3.5">
          <TopologyMark variant="mark" size={26} title="CodeSage" />
          <span className="cs-mono-label tracking-[0.12em]">CODESAGE</span>
        </header>

        <div>
          <div className="cs-mono-label mb-3">REPOSITORY INTELLIGENCE</div>
          <h1 className="font-display text-masthead italic text-text-primary">Repositories</h1>
          <p className="mt-3 max-w-[520px] font-display text-lede text-text-secondary">
            Import a GitHub repository to build structured engineering knowledge — symbols, a lightweight
            dependency graph, and a grounded Q&amp;A workspace.
          </p>
        </div>

        <form onSubmit={handleCreate} className="flex items-center gap-3 border-y border-border-subtle py-4">
          <BoxedInput
            value={githubUrl}
            onChange={(e) => setGithubUrl(e.target.value)}
            placeholder="https://github.com/owner/repository"
            aria-label="GitHub repository URL"
            disabled={createMutation.isPending}
          />
          <Button type="submit" variant="primary" loading={createMutation.isPending} disabled={!githubUrl.trim()}>
            Add repository
          </Button>
        </form>
        {createMutation.isError && (
          <ErrorPanel
            message={createMutation.error instanceof ApiError ? createMutation.error.message : "Couldn't import that repository."}
          />
        )}

        <section aria-label="Your repositories" className="flex flex-col">
          {isLoading &&
            Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="flex items-center justify-between border-t border-border-subtle py-4">
                <SkeletonLine width="220px" />
                <SkeletonLine width="90px" />
              </div>
            ))}

          {isError && <ErrorPanel message={error instanceof ApiError ? error.message : "Couldn't load repositories."} onRetry={() => refetch()} />}

          {!isLoading && !isError && repositories.length === 0 && (
            <EmptyState message="No repositories yet — add one above to get started." />
          )}

          {!isLoading &&
            repositories.map((repo) => (
              <div
                key={repo.id}
                className="flex items-center justify-between gap-4 border-t border-border-subtle py-4 last:border-b"
              >
                <Link href={`/r/${repo.id}`} className="min-w-0 flex-1">
                  <div className="font-display text-[17px] italic text-text-primary">{repo.name}</div>
                  <div className="mt-1 font-mono text-[10.5px] text-text-tertiary">
                    {repo.github_url} &middot; updated {formatRelativeTime(repo.updated_at)}
                  </div>
                </Link>
                <RepoStatusChip status={repo.status} indexingStatus={repo.indexing_status} />
                <button
                  aria-label={`Delete ${repo.name}`}
                  onClick={() => {
                    setPendingDeleteId(repo.id);
                    setConfirmText("");
                  }}
                  className="text-text-tertiary hover:text-danger"
                >
                  <Trash2 size={15} strokeWidth={1.6} />
                </button>
              </div>
            ))}
        </section>
      </div>

      <Modal
        open={Boolean(pendingDelete)}
        onOpenChange={(open) => !open && setPendingDeleteId(null)}
        title="Delete repository"
        description={`This removes ${pendingDelete?.name ?? "this repository"}'s local index — metadata, vectors, cached data. The original GitHub source is never touched.`}
      >
        <label className="block font-mono text-[10.5px] text-text-tertiary" htmlFor="confirm-delete">
          Type <span className="text-text-primary">{pendingDelete?.name}</span> to confirm
        </label>
        <BoxedInput
          id="confirm-delete"
          value={confirmText}
          onChange={(e) => setConfirmText(e.target.value)}
          className="mt-2"
        />
        <div className="mt-4 flex justify-end gap-3">
          <Button variant="ghost" onClick={() => setPendingDeleteId(null)}>
            Cancel
          </Button>
          <Button
            variant="danger"
            disabled={confirmText !== pendingDelete?.name}
            loading={deleteMutation.isPending}
            onClick={() => {
              if (!pendingDeleteId) return;
              deleteMutation.mutate(pendingDeleteId, { onSuccess: () => setPendingDeleteId(null) });
            }}
          >
            Delete repository
          </Button>
        </div>
      </Modal>
    </div>
  );
}
