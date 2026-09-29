"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowRight, Plus, Trash2 } from "lucide-react";
import { TopologyMark } from "@/components/devices/TopologyMark";
import { DeleteRepositoryDialog } from "@/components/domain/DeleteRepositoryDialog";
import { RepoStatusChip } from "@/components/domain/RepoStatusChip";
import { TopBar } from "@/components/nav/TopBar";
import { Button } from "@/components/ui/Button";
import { EmptyState, ErrorPanel, Notice } from "@/components/state/StateVocabulary";
import { ApiError } from "@/lib/api/client";
import { useCreateRepository, useRepositories } from "@/lib/query/repositories";
import type { Repository } from "@/lib/types/repository";
import { formatRelativeTime } from "@/lib/utils";

const SAMPLES = ["https://github.com/miguelgrinberg/microblog", "https://github.com/pallets/itsdangerous"];

/** Classifies an import failure by what the backend actually returned (prototype spec §4.10). */
function importErrorCopy(err: unknown): { title: string; hint: string } {
  if (!(err instanceof ApiError)) return { title: "Couldn't import that repository", hint: "" };
  if (err.kind === "network") return { title: "Can't reach the CodeSage backend", hint: "Check that the backend is running, then retry." };
  if (err.kind === "timeout")
    return {
      title: "Still cloning — the request timed out",
      hint: "Cloning and the file scan run inside the request. Large repositories can take longer than the client waits; the list refreshes and the repository appears once the clone finishes.",
    };
  if (err.status === 502)
    return {
      title: "The repository couldn't be cloned",
      hint: "CodeSage clones public GitHub repositories only — private repositories aren't supported yet. The entry below is kept as FAILED; delete it to try again.",
    };
  if (err.status === 409) return { title: "Already in your workspace", hint: "This URL is already registered." };
  return { title: "That URL can't be imported", hint: "Use a public repository URL of the form https://github.com/owner/repository." };
}

export default function RepositoriesPage() {
  const router = useRouter();
  const repos = useRepositories();
  const create = useCreateRepository();
  const [githubUrl, setGithubUrl] = useState("");
  const [name, setName] = useState("");
  const [toDelete, setToDelete] = useState<Repository | null>(null);
  const [readdUrl, setReaddUrl] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const urlRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!create.isPending) return;
    const started = Date.now();
    const iv = setInterval(() => setElapsed((Date.now() - started) / 1000), 100);
    return () => clearInterval(iv);
  }, [create.isPending]);

  // Keep chips live while any repository is still indexing.
  const anyIndexing = repos.data?.repositories.some((r) => r.indexing_status === "indexing" || r.status === "cloning");
  useEffect(() => {
    if (!anyIndexing) return;
    const iv = setInterval(() => repos.refetch(), 3_000);
    return () => clearInterval(iv);
  }, [anyIndexing, repos]);

  function submit(e: FormEvent) {
    e.preventDefault();
    const url = githubUrl.trim();
    if (!url || create.isPending) return;
    create.mutate(
      { github_url: url, name: name.trim() || undefined },
      {
        onSuccess: (repo) => {
          setGithubUrl("");
          setName("");
          router.push(`/r/${repo.id}`);
        },
        onError: () => urlRef.current?.focus(),
      },
    );
  }

  const list = repos.data?.repositories ?? [];
  const errCopy = create.isError ? importErrorCopy(create.error) : null;
  const existing = create.error instanceof ApiError && create.error.status === 409 ? list.find((r) => r.github_url === githubUrl.trim()) : undefined;

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <TopBar />
      <main className="cs-scrollbar min-h-0 flex-1 overflow-y-auto">
        <div className="cs-page cs-page-glow">
          <TopologyMark variant="watermark" />
          <div className="relative z-10 mx-auto max-w-[860px] px-5 pb-24 pt-12 sm:px-8 sm:pt-14">
            <p className="cs-mono-label">Repository intelligence</p>
            <h1 className="cs-masthead mt-2">Repositories</h1>
            <p className="cs-lede mt-4">
              Import a GitHub repository to build structured engineering knowledge — symbols, a lightweight dependency graph, and a grounded
              Q&amp;A workspace.
            </p>

            <form onSubmit={submit} noValidate className="mt-9 grid grid-cols-1 items-end gap-5 border-y border-border-subtle py-6 md:grid-cols-[minmax(0,1fr)_auto]">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-[minmax(0,1fr)_190px]">
                <label className="flex min-w-0 flex-col gap-1">
                  <span className="cs-mono-label !text-[10px]">GitHub repository URL</span>
                  <input
                    ref={urlRef}
                    value={githubUrl}
                    onChange={(e) => setGithubUrl(e.target.value)}
                    placeholder="https://github.com/owner/repository"
                    autoComplete="off"
                    spellCheck={false}
                    inputMode="url"
                    disabled={create.isPending}
                    className="cs-underline-input h-[42px] font-mono text-[13.5px]"
                  />
                </label>
                <label className="flex min-w-0 flex-col gap-1">
                  <span className="cs-mono-label !text-[10px]">
                    Display name <span className="normal-case tracking-normal">(optional)</span>
                  </span>
                  <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="defaults to repo name"
                    autoComplete="off"
                    disabled={create.isPending}
                    className="cs-underline-input h-[42px] text-[13.5px]"
                  />
                </label>
              </div>
              <Button type="submit" variant="primary" loading={create.isPending} disabled={!githubUrl.trim()}>
                {!create.isPending && <Plus size={15} aria-hidden="true" />}
                {create.isPending ? "Cloning and scanning…" : "Add repository"}
              </Button>
            </form>
            <div aria-live="polite">
              {create.isPending && (
                <div className="flex items-center gap-3 pt-3 font-mono text-[12px] text-text-secondary">
                  <span className="cs-indet w-[120px]" aria-hidden="true" />
                  git clone --depth 1 · then scanning files · <span className="cs-tabular">{elapsed.toFixed(1)}s</span>
                </div>
              )}
              {errCopy && (
                <Notice
                  tone={create.error instanceof ApiError && create.error.kind === "timeout" ? "warn" : "bad"}
                  title={errCopy.title}
                  className="mt-4"
                  actions={
                    existing && (
                      <Link href={`/r/${existing.id}`} className="cs-link">
                        Open it <ArrowRight size={13} aria-hidden="true" />
                      </Link>
                    )
                  }
                >
                  <div className="cs-errmono">
                    {create.error instanceof ApiError && create.error.status ? `HTTP ${create.error.status} · ` : ""}
                    {(create.error as Error).message}
                  </div>
                  {errCopy.hint && <p className="mt-2 text-small">{errCopy.hint}</p>}
                </Notice>
              )}
            </div>

            <div className="mt-12 flex items-baseline justify-between">
              <p className="cs-mono-label">
                Workspace{list.length ? ` · ${list.length} ${list.length === 1 ? "repository" : "repositories"}` : ""}
              </p>
              <Link href="/about" className="cs-link cs-link-quiet">
                How CodeSage works <ArrowRight size={13} aria-hidden="true" />
              </Link>
            </div>
            <section aria-label="Your repositories" className="mt-3">
              {repos.isLoading && (
                <div className="flex flex-col gap-3 pt-2">
                  {[0, 1, 2].map((i) => (
                    <div key={i} className="cs-skel h-[62px]" style={{ opacity: 1 - i * 0.2 }} />
                  ))}
                </div>
              )}
              {repos.isError && <ErrorPanel error={repos.error} onRetry={() => repos.refetch()} />}
              {repos.data && list.length === 0 && (
                <EmptyState
                  message="No repositories yet — add one above to get started."
                  detail={
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-text-tertiary">Try a public sample:</span>
                      {SAMPLES.map((u) => (
                        <button key={u} className="cs-chipbtn" onClick={() => { setGithubUrl(u); urlRef.current?.focus(); }}>
                          {u.replace("https://github.com/", "")}
                        </button>
                      ))}
                    </div>
                  }
                />
              )}
              {list.length > 0 && (
                <div className="cs-rows">
                  {list.map((repo) => {
                    const failed = repo.status === "failed";
                    return (
                      <div key={repo.id} className="cs-hover-row -mx-3 grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 py-[18px] pl-4 pr-3 sm:grid-cols-[minmax(0,1fr)_auto_auto]">
                        <div className="min-w-0">
                          {failed ? (
                            <span className="font-display text-[19px] italic text-text-primary">{repo.name}</span>
                          ) : (
                            <Link href={`/r/${repo.id}`} className="rounded font-display text-[19px] italic text-text-primary hover:text-[var(--cs-accent-violet-hover)]">
                              {repo.name}
                            </Link>
                          )}
                          <div className="mt-0.5 break-all font-mono text-[11.5px] text-text-tertiary">
                            {repo.github_url} · updated {formatRelativeTime(repo.updated_at)}
                          </div>
                          {repo.error_message && (
                            <div className={`mt-1.5 max-w-[66ch] break-words font-mono text-[11px] ${failed ? "text-danger" : "text-warning"}`}>
                              {repo.error_message.split("\n")[0]}
                            </div>
                          )}
                        </div>
                        <div className="col-start-1 row-start-2 sm:col-start-auto sm:row-start-auto">
                          <RepoStatusChip status={repo.status} indexingStatus={repo.indexing_status} updatedAt={repo.updated_at} />
                        </div>
                        <div className="col-start-2 row-span-2 row-start-1 flex items-center gap-1 sm:col-start-auto sm:row-span-1 sm:row-start-auto">
                          {failed && (
                            <Button size="sm" variant="ghost" onClick={() => { setReaddUrl(repo.github_url); setToDelete(repo); }}>
                              Delete &amp; re-add
                            </Button>
                          )}
                          <button
                            aria-label={`Delete ${repo.name}`}
                            title="Delete local index"
                            onClick={() => { setReaddUrl(null); setToDelete(repo); }}
                            className="grid h-9 w-9 place-items-center rounded-[8px] text-text-tertiary transition-colors hover:bg-surface-2 hover:text-danger"
                          >
                            <Trash2 size={15} strokeWidth={1.6} aria-hidden="true" />
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </section>
          </div>
        </div>
      </main>
      <DeleteRepositoryDialog
        repository={toDelete}
        onClose={() => setToDelete(null)}
        onDeleted={() => {
          if (readdUrl) {
            setGithubUrl(readdUrl);
            create.reset();
            requestAnimationFrame(() => urlRef.current?.focus());
          }
        }}
      />
    </div>
  );
}
