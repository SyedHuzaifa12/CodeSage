"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowRight, Plus, Trash2 } from "lucide-react";
import { GuestBanner } from "@/components/auth/GuestBanner";
import { DeleteRepositoryDialog } from "@/components/domain/DeleteRepositoryDialog";
import { RepoStatusChip } from "@/components/domain/RepoStatusChip";
import { TopBar } from "@/components/nav/TopBar";
import { Button } from "@/components/ui/Button";
import { ErrorPanel, Notice } from "@/components/state/StateVocabulary";
import { useAuth } from "@/context/AuthContext";
import { ApiError } from "@/lib/api/client";
import { demoQuestions } from "@/lib/demo";
import { useCreateRepository, useRepositories } from "@/lib/query/repositories";
import { isRepositoryReady, type Repository } from "@/lib/types/repository";
import { formatRelativeTime } from "@/lib/utils";

const SAMPLES = ["https://github.com/miguelgrinberg/microblog", "https://github.com/pallets/itsdangerous"];

/** Classifies an import failure by what the backend actually returned (prototype spec §4.10). */
function importErrorCopy(err: unknown): { title: string; hint: string } {
  if (!(err instanceof ApiError)) return { title: "Couldn't import that repository", hint: "" };
  if (err.kind === "network") return { title: "Can't reach the CodeSage backend", hint: "Check that the backend is running, then retry." };
  if (err.kind === "timeout")
    return {
      title: "That's taking longer than expected",
      hint: "The server may be waking up (free hosting sleeps when idle) or the repository is large. Your repository appears in the list below as soon as it is registered.",
    };
  if (err.code === "GUEST_QUOTA_EXCEEDED")
    return { title: "Guest limit reached", hint: "Sign in with GitHub to index more repositories — the one you already indexed is kept." };
  if (err.code === "RATE_LIMITED") return { title: "Limit reached for now", hint: err.message };
  if (err.status === 413)
    return {
      title: "That repository is too large for guest sessions",
      hint: "Guests can index smaller repositories. Sign in with GitHub to index larger ones.",
    };
  if (err.status === 502)
    return {
      title: "The repository couldn't be cloned",
      hint: "CodeSage clones public GitHub repositories only — private repositories aren't supported yet. The entry below is marked as failed; delete it to try again.",
    };
  if (err.status === 409) return { title: "Already in your workspace", hint: "This URL is already registered." };
  return { title: "That URL can't be imported", hint: "Use a public repository URL of the form https://github.com/owner/repository." };
}

export default function RepositoriesPage() {
  const router = useRouter();
  const repos = useRepositories();
  const create = useCreateRepository();
  const { isGuest, quota, openSignIn } = useAuth();
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
  const anyIndexing = repos.data?.repositories.some((r) => r.indexing_status === "indexing" || r.status === "cloning");  useEffect(() => {
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

  const allRepos = repos.data?.repositories ?? [];
  const demo = allRepos.find((r) => r.is_demo);
  const list = allRepos.filter((r) => !r.is_demo); // the demo has its own card below
  // A guest who has used their free repository can't add another until they sign in.
  const locked = isGuest && quota !== undefined && quota.repositories_used >= quota.repositories_limit;
  const errCopy = create.isError ? importErrorCopy(create.error) : null;
  const existing = create.error instanceof ApiError && create.error.status === 409 ? list.find((r) => r.github_url === githubUrl.trim()) : undefined;

  const hasDemo = Boolean(demo) || repos.isLoading;
  const primaryLink =
    "inline-flex min-h-[38px] items-center justify-center gap-2 whitespace-nowrap rounded-[8px] border border-transparent bg-[var(--cs-accent-violet)] px-4 text-[13.5px] font-medium text-[var(--cs-on-accent)] shadow-sm transition-colors hover:bg-[var(--cs-accent-violet-hover)]";

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <TopBar />
      <GuestBanner />
      <main className="cs-scrollbar min-h-0 flex-1 overflow-y-auto">
        <div className="cs-page">
          <div className="mx-auto max-w-[1040px] px-5 pb-20 pt-10 sm:px-8 sm:pt-14">
            <header className="max-w-[720px]">
              <h1 className="cs-masthead">Understand any codebase, faster</h1>
              <p className="cs-lede mt-3">
                Import a public GitHub repository and CodeSage maps its structure and dependencies, then answers your questions with
                citations to the exact source lines.
              </p>
              <Link href="/about" className="cs-link mt-4">
                How it works <ArrowRight size={14} aria-hidden="true" />
              </Link>
            </header>

            <div className={`mt-9 grid gap-5 ${hasDemo ? "lg:grid-cols-2" : ""}`}>
              {hasDemo && (
                <section aria-labelledby="demo-heading" className="cs-card flex flex-col p-6">
                  {demo ? (
                    <>
                      <span className="cs-pill cs-pill-semantic self-start">Fastest way to start</span>
                      <h2 id="demo-heading" className="mt-3 text-h1 font-semibold text-text-primary">
                        Try the {demo.name} demo
                      </h2>
                      <p className="mt-1.5 text-[14px] text-text-secondary">
                        Already indexed, so there is nothing to import or wait for. Explore its architecture and ask questions about the code.
                      </p>
                      {isRepositoryReady(demo) && (
                        <div className="mt-4">
                          <p className="text-small font-medium text-text-tertiary">Try asking</p>
                          <div className="mt-2 flex flex-wrap gap-2">
                            {demoQuestions(demo.github_url).map((q) => (
                              <Link key={q} href={`/r/${demo.id}/ask?q=${encodeURIComponent(q)}`} className="cs-qchip">
                                {q}
                              </Link>
                            ))}
                          </div>
                        </div>
                      )}
                      <div className="mt-6 pt-1">
                        <Link href={`/r/${demo.id}`} className={primaryLink}>
                          Open the demo <ArrowRight size={15} aria-hidden="true" />
                        </Link>
                      </div>
                    </>
                  ) : (
                    <div className="flex flex-col gap-3" aria-busy="true">
                      <div className="cs-skel h-5 w-32" />
                      <div className="cs-skel h-7 w-3/4" />
                      <div className="cs-skel h-4 w-full" />
                      <div className="cs-skel h-9 w-40" />
                    </div>
                  )}
                </section>
              )}

              <section aria-labelledby="import-heading" className="cs-card p-6">
                <h2 id="import-heading" className="text-h1 font-semibold text-text-primary">
                  Import a repository
                </h2>
                <p className="mt-1.5 text-[14px] text-text-secondary">
                  Paste the URL of a public GitHub repository.
                  {isGuest && quota
                    ? ` Guests can import ${quota.repositories_limit} ${quota.repositories_limit === 1 ? "repository" : "repositories"}; sign in with GitHub for more.`
                    : ""}
                </p>
                <form onSubmit={submit} noValidate className="mt-5 flex flex-col gap-4">
                  <label className="flex min-w-0 flex-col gap-1.5">
                    <span className="text-small font-medium text-text-secondary">Repository URL</span>
                    <input
                      ref={urlRef}
                      value={githubUrl}
                      onChange={(e) => setGithubUrl(e.target.value)}
                      placeholder="https://github.com/owner/repository"
                      autoComplete="off"
                      spellCheck={false}
                      inputMode="url"
                      disabled={create.isPending}
                      className="cs-underline-input h-[42px] font-mono text-[13px]"
                    />
                  </label>
                  <label className="flex min-w-0 flex-col gap-1.5">
                    <span className="text-small font-medium text-text-secondary">
                      Display name <span className="font-normal text-text-tertiary">(optional)</span>
                    </span>
                    <input
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder="Defaults to the repository name"
                      autoComplete="off"
                      disabled={create.isPending}
                      className="cs-underline-input h-[42px] text-[14px]"
                    />
                  </label>
                  <div className="flex flex-wrap items-center gap-3">
                    <Button type="submit" variant="primary" loading={create.isPending} disabled={!githubUrl.trim() || locked}>
                      {!create.isPending && <Plus size={15} aria-hidden="true" />}
                      {create.isPending ? "Importing…" : "Import repository"}
                    </Button>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-small text-text-tertiary">Or try:</span>
                      {SAMPLES.map((u) => (
                        <button
                          key={u}
                          type="button"
                          className="cs-chipbtn"
                          onClick={() => {
                            setGithubUrl(u);
                            urlRef.current?.focus();
                          }}
                        >
                          {u.replace("https://github.com/", "")}
                        </button>
                      ))}
                    </div>
                  </div>
                </form>
                {locked && (
                  <Notice
                    title="You've used your free repository"
                    className="mt-4"
                    actions={
                      <Button size="sm" variant="primary" onClick={() => openSignIn()}>
                        Continue with GitHub
                      </Button>
                    }
                  >
                    Sign in to keep it and import more. You can still explore it and the demo.
                  </Notice>
                )}
                <div aria-live="polite">
                  {create.isPending && (
                    <div className="mt-4 flex items-center gap-3 text-[13px] text-text-secondary">
                      <span className="cs-indet w-[96px]" aria-hidden="true" />
                      Registering your repository… <span className="cs-tabular">{elapsed.toFixed(1)}s</span>
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
              </section>
            </div>

            <section aria-labelledby="repos-heading" className="mt-12">
              <div className="flex items-baseline justify-between gap-4">
                <h2 id="repos-heading" className="text-h1 font-semibold text-text-primary">
                  Your repositories
                  {list.length > 0 && <span className="ml-2 text-[14px] font-normal text-text-tertiary">{list.length}</span>}
                </h2>
              </div>

              <div className="mt-4">
                {repos.isLoading && (
                  <div className="flex flex-col gap-3">
                    {[0, 1].map((i) => (
                      <div key={i} className="cs-skel h-[66px]" style={{ opacity: 1 - i * 0.25 }} />
                    ))}
                  </div>
                )}
                {repos.isError && <ErrorPanel error={repos.error} onRetry={() => repos.refetch()} />}
                {repos.data && list.length === 0 && (
                  <div className="rounded-[10px] border border-dashed border-border-strong px-6 py-10 text-center">
                    <p className="text-[15px] font-medium text-text-primary">No repositories yet</p>
                    <p className="mx-auto mt-1 max-w-[46ch] text-[14px] text-text-secondary">
                      Import one above, or open the demo to see what CodeSage produces.
                    </p>
                  </div>
                )}
                {list.length > 0 && (
                  <div className="cs-card overflow-hidden">
                    <div className="hidden grid-cols-[minmax(0,1fr)_150px_120px_88px] gap-x-4 border-b border-border-subtle bg-surface-2 px-5 py-2.5 text-small font-medium text-text-tertiary sm:grid">
                      <span>Repository</span>
                      <span>Status</span>
                      <span>Updated</span>
                      <span className="sr-only">Actions</span>
                    </div>
                    <ul className="divide-y divide-border-subtle">
                      {list.map((repo) => {
                        const failed = repo.status === "failed" || repo.indexing_status === "failed";
                        return (
                          <li
                            key={repo.id}
                            className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 px-5 py-4 transition-colors hover:bg-surface-2 sm:grid-cols-[minmax(0,1fr)_150px_120px_88px]"
                          >
                            <div className="min-w-0">
                              {repo.status === "failed" ? (
                                <span className="text-[15px] font-semibold text-text-primary">{repo.name}</span>
                              ) : (
                                <Link href={`/r/${repo.id}`} className="rounded text-[15px] font-semibold text-text-primary hover:text-violet">
                                  {repo.name}
                                </Link>
                              )}
                              <div className="mt-0.5 truncate font-mono text-[12px] text-text-tertiary">{repo.github_url}</div>
                              {repo.error_message && (
                                <div className={`mt-1.5 max-w-[70ch] break-words text-[12.5px] ${failed ? "text-danger" : "text-warning"}`}>
                                  {repo.error_message.split("\n")[0]}
                                </div>
                              )}
                            </div>
                            <div className="col-start-1 row-start-2 sm:col-start-auto sm:row-start-auto">
                              <RepoStatusChip status={repo.status} indexingStatus={repo.indexing_status} updatedAt={repo.updated_at} />
                            </div>
                            <div className="hidden text-[13px] text-text-secondary sm:block">{formatRelativeTime(repo.updated_at)}</div>
                            <div className="col-start-2 row-span-2 row-start-1 flex items-center justify-end gap-1 sm:col-start-auto sm:row-span-1 sm:row-start-auto">
                              {repo.status === "failed" && (
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={() => {
                                    setReaddUrl(repo.github_url);
                                    setToDelete(repo);
                                  }}
                                >
                                  Delete &amp; re-add
                                </Button>
                              )}
                              <button
                                aria-label={`Delete ${repo.name}`}
                                title="Delete this repository"
                                onClick={() => {
                                  setReaddUrl(null);
                                  setToDelete(repo);
                                }}
                                className="grid h-9 w-9 place-items-center rounded-[8px] text-text-tertiary transition-colors hover:bg-surface-3 hover:text-danger"
                              >
                                <Trash2 size={15} strokeWidth={1.6} aria-hidden="true" />
                              </button>
                            </div>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                )}
              </div>
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
