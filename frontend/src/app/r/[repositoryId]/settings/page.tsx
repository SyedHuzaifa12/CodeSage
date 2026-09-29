"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, ChevronDown, RefreshCw, Trash2 } from "lucide-react";
import { useRepositoryContext } from "@/context/RepositoryContext";
import { DeleteRepositoryDialog } from "@/components/domain/DeleteRepositoryDialog";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { ErrorPanel, Notice } from "@/components/state/StateVocabulary";
import { ApiError } from "@/lib/api/client";
import { fetchHealth } from "@/lib/api/health";
import { useChunks, useKnowledgeState, useReindex } from "@/lib/query/knowledge";
import { queryKeys } from "@/lib/query/keys";
import { useUpdateRepositoryName } from "@/lib/query/repositories";
import { useRefreshWorkspace, useResetWorkspace } from "@/lib/query/workspace";
import { cn, formatNumber, formatRelativeTime } from "@/lib/utils";

const CHUNK_TYPES = ["all", "symbol", "symbol_split", "fallback"] as const;
const PAGE = 50;

function ConfirmDialog({
  open,
  title,
  body,
  action,
  danger,
  loading,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  body: string;
  action: string;
  danger?: boolean;
  loading?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title={title} description={body}>
      <div className="mt-2 flex justify-end gap-2.5">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} loading={loading}>
          {action}
        </Button>
      </div>
    </Modal>
  );
}

function ChunkBrowser({ repositoryId }: { repositoryId: string }) {
  const [type, setType] = useState<(typeof CHUNK_TYPES)[number]>("all");
  const [offset, setOffset] = useState(0);
  const chunks = useChunks(repositoryId, { chunkType: type === "all" ? undefined : type, limit: PAGE, offset });
  const rows = chunks.data?.chunks ?? [];
  return (
    <div className="cs-fade-in mt-3">
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Chunk type">
        {CHUNK_TYPES.map((t) => (
          <button key={t} className="cs-chipbtn" aria-pressed={type === t} onClick={() => { setType(t); setOffset(0); }}>
            {t}
          </button>
        ))}
      </div>
      {chunks.isError && <ErrorPanel className="mt-3" error={chunks.error} onRetry={() => chunks.refetch()} />}
      <div className="cs-scrollbar mt-3 overflow-x-auto">
        <table className="w-full border-collapse font-mono text-[11.5px]">
          <thead>
            <tr>
              {["chunk", "type", "lines", "chars", "language", "hash"].map((h) => (
                <th key={h} className="whitespace-nowrap border-b border-border-strong py-2 pr-3 text-left text-[10px] font-medium uppercase tracking-[0.08em] text-text-tertiary">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {chunks.isLoading &&
              [0, 1, 2, 3].map((i) => (
                <tr key={i}>
                  <td colSpan={6} className="py-1.5">
                    <div className="cs-skel h-5" />
                  </td>
                </tr>
              ))}
            {rows.map((c) => (
              <tr key={c.id} className="text-text-secondary">
                <td className="whitespace-nowrap border-b border-border-subtle py-[7px] pr-3">#{c.chunk_index}</td>
                <td className="whitespace-nowrap border-b border-border-subtle py-[7px] pr-3">{c.chunk_type}</td>
                <td className="whitespace-nowrap border-b border-border-subtle py-[7px] pr-3">
                  {c.start_line}–{c.end_line}
                </td>
                <td className="cs-tabular whitespace-nowrap border-b border-border-subtle py-[7px] pr-3">{c.char_count.toLocaleString("en-US")}</td>
                <td className="whitespace-nowrap border-b border-border-subtle py-[7px] pr-3">{c.language ?? "—"}</td>
                <td className="whitespace-nowrap border-b border-border-subtle py-[7px] pr-3">{c.content_hash.slice(0, 10)}</td>
              </tr>
            ))}
            {chunks.data && rows.length === 0 && (
              <tr>
                <td colSpan={6} className="py-4 text-text-tertiary">
                  No chunks of this type.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <span className="cs-monoline !text-[11px]">
          limit {PAGE} · offset {offset}
        </span>
        <span className="flex gap-1.5">
          <Button size="sm" variant="ghost" disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - PAGE))}>
            Previous
          </Button>
          <Button size="sm" variant="ghost" disabled={rows.length < PAGE} onClick={() => setOffset((o) => o + PAGE)}>
            Next
          </Button>
        </span>
      </div>
      <p className="mt-2 text-small text-text-tertiary">Chunk metadata only — the API never returns chunk text.</p>
    </div>
  );
}

export default function SettingsPage() {
  const { repositoryId, repository, isReady } = useRepositoryContext();
  const router = useRouter();
  const client = useQueryClient();
  const [waitingSince, setWaitingSince] = useState<string | null | undefined>(undefined);
  const knowledge = useKnowledgeState(repositoryId, { poll: waitingSince !== undefined });
  const reindex = useReindex();
  const refresh = useRefreshWorkspace();
  const reset = useResetWorkspace();
  const rename = useUpdateRepositoryName();
  const health = useQuery({ queryKey: ["health"], queryFn: () => fetchHealth(), refetchInterval: 30_000, retry: false });
  const [name, setName] = useState("");
  const [confirm, setConfirm] = useState<"reindex" | "reset" | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [chunksOpen, setChunksOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const reindexStarted = useRef(0);

  useEffect(() => {
    if (repository) setName(repository.name);
  }, [repository]);

  // The reindex pipeline commits once at the end, so completion shows up only
  // as a new last_indexed_at — watch for that change (with a ceiling).
  useEffect(() => {
    if (waitingSince === undefined || !knowledge.data) return;
    if (knowledge.data.last_indexed_at !== waitingSince) {
      setWaitingSince(undefined);
      const K = knowledge.data;
      setNotice(`Knowledge re-indexed — ${K.total_files_skipped_unchanged} files unchanged, ${K.total_chunks_from_cache} chunks from cache, ${K.total_chunks_embedded_fresh} embedded fresh.`);
      client.invalidateQueries({ queryKey: ["repositories", repositoryId, "reports"] });
    } else if (Date.now() - reindexStarted.current > 10 * 60_000) {
      setWaitingSince(undefined);
      setNotice("Still waiting for the reindex to finish — refresh this page later.");
    }
  }, [knowledge.data, waitingSince, client, repositoryId]);

  if (!repository) {
    return (
      <div className="mx-auto max-w-[680px] px-7 py-11">
        <div className="cs-skel h-10 w-2/3" />
        <div className="cs-skel mt-6 h-40" />
      </div>
    );
  }

  const K = knowledge.data;
  const notIndexed = knowledge.isError && knowledge.error instanceof ApiError && knowledge.error.status === 404;
  const reindexing = waitingSince !== undefined;
  const timings = K
    ? ([
        ["chunking", K.chunking_ms ?? 0, "var(--cs-accent-cyan)"],
        ["embedding", K.embedding_ms ?? 0, "var(--cs-accent-violet)"],
        ["upsert", K.upsert_ms ?? 0, "var(--cs-warning)"],
      ] as const)
    : [];

  function onRename(e: FormEvent) {
    e.preventDefault();
    const v = name.trim();
    if (!v || v === repository?.name) return;
    rename.mutate({ id: repositoryId, name: v }, { onSuccess: () => setNotice("Name saved.") });
  }

  return (
    <div className="cs-page">
      <div className="mx-auto max-w-[680px] px-5 pb-28 pt-11 sm:px-7">
        <p className="cs-mono-label">Index &amp; settings</p>
        <h1 className="cs-display mt-2">{repository.name}</h1>
        {repository.github_url && <p className="cs-monoline mt-2">{repository.github_url}</p>}
        <div aria-live="polite">{notice && <Notice className="mt-5">{notice}</Notice>}</div>

        <section className="mt-8 border-t border-border-subtle pt-7" aria-labelledby="kih">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 id="kih" className="font-sans text-[17px] font-semibold text-text-primary">
              Knowledge index health
            </h2>
            {K && (
              <span className={cn("cs-chip", reindexing ? "border-[var(--cs-violet-line)] bg-[var(--cs-violet-tint)] text-violet" : "border-success/35 bg-success/[0.06] text-success")}>
                <span className={cn("cs-chip-dot", reindexing && "cs-pulse")} aria-hidden="true" />
                {reindexing ? "re-indexing" : K.status}
              </span>
            )}
          </div>
          {knowledge.isLoading && <div className="cs-skel mt-4 h-32" />}
          {notIndexed && (
            <p className="py-6 text-text-secondary">
              Not indexed yet.{" "}
              <Link className="cs-link" href={`/r/${repositoryId}`}>
                Start indexing on Overview <ArrowRight size={13} aria-hidden="true" />
              </Link>
            </p>
          )}
          {knowledge.isError && !notIndexed && <ErrorPanel className="mt-4" error={knowledge.error} onRetry={() => knowledge.refetch()} />}
          {K && (
            <>
              <div className="cs-statstrip mt-4">
                <div>
                  <span className="cs-mono-label">Chunks</span>
                  <span className="cs-statval">{formatNumber(K.total_chunks)}</span>
                </div>
                <div className="min-w-0">
                  <span className="cs-mono-label">Model</span>
                  <span className="cs-statval !text-[12.5px]">{K.embedding_model_version ?? "—"}</span>
                </div>
                <div>
                  <span className="cs-mono-label">Last indexed</span>
                  <span className="cs-statval">{formatRelativeTime(K.last_indexed_at)}</span>
                </div>
              </div>
              <dl className="cs-kv mt-4">
                <dt>files considered</dt>
                <dd>{K.total_files_considered}</dd>
                <dt>skipped (unchanged)</dt>
                <dd>{K.total_files_skipped_unchanged}</dd>
                <dt>failed</dt>
                <dd className={K.total_files_failed ? "text-danger" : undefined}>{K.total_files_failed}</dd>
                <dt>chunks from cache</dt>
                <dd>{K.total_chunks_from_cache}</dd>
                <dt>embedded fresh</dt>
                <dd>{K.total_chunks_embedded_fresh}</dd>
                <dt>total</dt>
                <dd>{K.total_ms != null ? `${K.total_ms.toLocaleString("en-US")} ms` : "—"}</dd>
              </dl>
              {K.total_ms ? (
                <>
                  <div className="cs-latbar mt-4" aria-hidden="true">
                    {timings.map(([k, v, c]) => (
                      <i key={k} style={{ flex: Math.max(v, 1), background: c }} />
                    ))}
                  </div>
                  <div className="mt-2 flex flex-wrap gap-x-3.5 gap-y-1 font-mono text-[10.5px] text-text-tertiary">
                    {timings.map(([k, v, c]) => (
                      <span key={k}>
                        <i className="cs-legend-dot" style={{ background: c }} aria-hidden="true" />
                        {k} {v.toLocaleString("en-US")}ms
                      </span>
                    ))}
                  </div>
                </>
              ) : null}
              {K.error_message && (
                <Notice tone="warn" className="mt-4">
                  {K.error_message}
                </Notice>
              )}
              <div className="mt-6">
                <Button variant="secondary" loading={reindexing || reindex.isPending} onClick={() => setConfirm("reindex")}>
                  {!reindexing && <RefreshCw size={14} aria-hidden="true" />}
                  {reindexing ? "Re-indexing…" : "Reindex knowledge"}
                </Button>
              </div>
              <p className="mt-3 text-small text-text-tertiary">
                Re-chunks and re-embeds, skipping unchanged files by content hash. It doesn&rsquo;t re-parse or pull from GitHub. Every reindex marks all
                reports <span className="text-warning">stale</span> and invalidates cached answers.
              </p>
              {reindex.isError && <ErrorPanel className="mt-3" error={reindex.error} />}
            </>
          )}
        </section>

        <section className="mt-2 border-t border-border-subtle pt-7" aria-labelledby="rnh">
          <h2 id="rnh" className="font-sans text-[17px] font-semibold text-text-primary">
            Repository name
          </h2>
          <form onSubmit={onRename} className="mt-4 flex items-center gap-3">
            <label htmlFor="rename" className="sr-only">
              Display name
            </label>
            <input id="rename" value={name} onChange={(e) => setName(e.target.value)} className="cs-underline-input h-10 flex-1 text-[14px]" />
            <Button type="submit" variant="secondary" loading={rename.isPending} disabled={!name.trim() || name.trim() === repository.name}>
              Save name
            </Button>
          </form>
          {rename.isError && <ErrorPanel className="mt-3" error={rename.error} />}
        </section>

        <section className="mt-8 border-t border-border-subtle pt-7" aria-labelledby="advh">
          <h2 id="advh" className="font-sans text-[17px] font-semibold text-text-primary">
            Advanced
          </h2>
          <p className="mt-1 text-small text-text-tertiary">Maintenance endpoints that exist in the API.</p>
          <div className="mt-4 border-t border-border-subtle">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-subtle py-3.5">
              <div>
                <div className="text-[14.5px] font-semibold">Refresh file scan</div>
                <p className="text-small text-text-secondary">Re-walks the local clone without re-cloning.</p>
              </div>
              <Button
                size="sm"
                variant="secondary"
                loading={refresh.isPending}
                onClick={() => refresh.mutate(repositoryId, { onSuccess: (w) => setNotice(`File scan refreshed · ${w.total_files} files, ${w.folder_count} folders.`) })}
              >
                Refresh
              </Button>
            </div>
            {refresh.isError && <ErrorPanel className="my-3" error={refresh.error} />}
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-subtle py-3.5">
              <div>
                <div className="text-[14.5px] font-semibold">Reset index</div>
                <p className="text-small text-text-secondary">Wipes symbols, relationships, chunks and vectors. Keeps the clone.</p>
              </div>
              <Button size="sm" variant="danger-ghost" disabled={!isReady} onClick={() => setConfirm("reset")}>
                Reset
              </Button>
            </div>
            {reset.isError && <ErrorPanel className="my-3" error={reset.error} />}
            <div className="border-b border-border-subtle py-3.5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-[14.5px] font-semibold">Chunk browser</div>
                  <p className="text-small text-text-secondary">Paginated chunk metadata from GET /knowledge/chunks.</p>
                </div>
                <button className="cs-disclosure-btn" onClick={() => setChunksOpen((v) => !v)} aria-expanded={chunksOpen} disabled={!K}>
                  {chunksOpen ? "hide" : "browse"} <ChevronDown size={12} aria-hidden="true" />
                </button>
              </div>
              {chunksOpen && K && <ChunkBrowser repositoryId={repositoryId} />}
            </div>
            <div className="py-3.5">
              <div className="text-[14.5px] font-semibold">System health</div>
              {health.isLoading && <div className="cs-skel mt-3 h-5 w-2/3" />}
              {health.isError && <p className="mt-2 text-small text-danger">GET /health failed — the backend is unreachable.</p>}
              {health.data?.data && (
                <>
                  <div className="mt-3 flex flex-wrap gap-[18px] font-mono text-[12px]">
                    {Object.entries(health.data.data.dependencies).map(([k, ok]) => (
                      <span key={k} className="inline-flex items-center gap-2">
                        <i className={cn("h-[7px] w-[7px] rounded-full", ok ? "bg-success" : "bg-danger")} aria-hidden="true" />
                        {k} {ok ? "ok" : "unreachable"}
                      </span>
                    ))}
                  </div>
                  <p className="cs-monoline mt-2 !text-[11px]">
                    GET /health · {health.data.data.app_name} {health.data.data.version} · {health.data.data.environment} · uptime{" "}
                    {Math.floor(health.data.data.uptime_seconds / 3600)}h {Math.floor((health.data.data.uptime_seconds % 3600) / 60)}m
                  </p>
                </>
              )}
            </div>
          </div>
        </section>

        <section className="mt-8 border-t border-danger/45 pt-7" aria-labelledby="dzh">
          <h2 id="dzh" className="font-sans text-[17px] font-semibold text-danger">
            Danger zone
          </h2>
          <p className="mt-2 text-small text-text-secondary">
            Deletes this repository&rsquo;s local index — metadata, vectors, cached data. The original GitHub source is never touched.
          </p>
          <Button variant="danger-ghost" className="mt-4" onClick={() => setDeleting(true)}>
            <Trash2 size={14} aria-hidden="true" />
            Delete repository
          </Button>
        </section>
        <p className="mt-9 text-small text-text-tertiary">
          There&rsquo;s no &ldquo;pull latest from GitHub&rdquo;: clones are never updated. To index newer code, delete and re-add the repository.
        </p>
      </div>

      <ConfirmDialog
        open={confirm === "reindex"}
        title="Reindex knowledge"
        body="Unchanged files are skipped, so this is usually fast. All five reports will be marked stale and cached answers invalidated."
        action="Reindex knowledge"
        loading={reindex.isPending}
        onClose={() => setConfirm(null)}
        onConfirm={() =>
          reindex.mutate(repositoryId, {
            onSuccess: () => {
              reindexStarted.current = Date.now();
              setWaitingSince(K?.last_indexed_at ?? null);
              setNotice(null);
              setConfirm(null);
            },
          })
        }
      />
      <ConfirmDialog
        open={confirm === "reset"}
        title="Reset index"
        body="Symbols, relationships, chunks and vectors are wiped and the repository returns to “not indexed”. The clone is kept, so you can start indexing again."
        action="Reset index"
        danger
        loading={reset.isPending}
        onClose={() => setConfirm(null)}
        onConfirm={() =>
          reset.mutate(repositoryId, {
            onSuccess: () => {
              setConfirm(null);
              client.removeQueries({ queryKey: queryKeys.knowledgeState(repositoryId) });
              router.push(`/r/${repositoryId}`);
            },
          })
        }
      />
      <DeleteRepositoryDialog repository={deleting ? repository : null} onClose={() => setDeleting(false)} onDeleted={() => router.push("/")} />
    </div>
  );
}
