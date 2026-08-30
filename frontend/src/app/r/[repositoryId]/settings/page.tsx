"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useRepositoryContext } from "@/context/RepositoryContext";
import { Button } from "@/components/ui/Button";
import { BoxedInput } from "@/components/ui/Input";
import { Modal } from "@/components/ui/Modal";
import { SkeletonBlock } from "@/components/state/Loading";
import { ErrorPanel } from "@/components/state/StateVocabulary";
import { InlineStat } from "@/components/domain/StatTile";
import { useKnowledgeState, useReindex } from "@/lib/query/knowledge";
import { useDeleteRepository, useUpdateRepositoryName } from "@/lib/query/repositories";
import { ApiError } from "@/lib/api/client";
import { formatRelativeTime } from "@/lib/utils";

export default function SettingsPage() {
  const { repositoryId, repository } = useRepositoryContext();
  const router = useRouter();
  const knowledge = useKnowledgeState(repositoryId);
  const reindex = useReindex();
  const updateName = useUpdateRepositoryName();
  const deleteRepo = useDeleteRepository();

  const [name, setName] = useState(repository?.name ?? "");
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");

  // `repository` arrives asynchronously (RepositoryProvider's own fetch),
  // so useState's initializer above only catches it if it happened to
  // already be loaded on first render. Sync explicitly once it resolves —
  // otherwise this field renders permanently empty on a fresh page load.
  useEffect(() => {
    if (repository) setName(repository.name);
  }, [repository]);

  if (!repository) return <SkeletonBlock className="m-11" />;

  return (
    <div className="mx-auto flex max-w-[640px] flex-col gap-10 px-11 py-10">
      <h1 className="font-display text-display italic text-text-primary">Index &amp; Settings</h1>

      <section className="border-t border-border-subtle pt-5">
        <h2 className="font-sans text-h2 font-semibold text-text-primary">Knowledge index health</h2>
        {knowledge.isLoading && <SkeletonBlock className="mt-3" />}
        {knowledge.isError && (
          <ErrorPanel className="mt-3" message={knowledge.error instanceof ApiError ? knowledge.error.message : "Not indexed yet."} />
        )}
        {knowledge.data && (
          <>
            <div className="mt-4 flex flex-wrap gap-7">
              <InlineStat label="CHUNKS" value={String(knowledge.data.total_chunks)} />
              <InlineStat label="MODEL" value={knowledge.data.embedding_model_version ?? "—"} />
              <InlineStat label="LAST INDEXED" value={formatRelativeTime(knowledge.data.last_indexed_at)} />
            </div>
            <Button
              variant="secondary"
              className="mt-4"
              loading={reindex.isPending}
              onClick={() => reindex.mutate(repositoryId)}
            >
              Reindex knowledge
            </Button>
          </>
        )}
      </section>

      <section className="border-t border-border-subtle pt-5">
        <h2 className="font-sans text-h2 font-semibold text-text-primary">Repository name</h2>
        <div className="mt-3 flex gap-3">
          <BoxedInput value={name} onChange={(e) => setName(e.target.value)} />
          <Button
            variant="secondary"
            loading={updateName.isPending}
            disabled={!name.trim() || name === repository.name}
            onClick={() => updateName.mutate({ id: repositoryId, name: name.trim() })}
          >
            Save
          </Button>
        </div>
      </section>

      <section className="border-t border-danger/25 pt-5">
        <h2 className="font-sans text-h2 font-semibold text-danger">Danger zone</h2>
        <p className="mt-2 text-small text-text-secondary">
          Deletes this repository&rsquo;s local index — metadata, vectors, cached data. The original GitHub source is
          never touched.
        </p>
        <Button variant="danger" className="mt-3" onClick={() => setDeleteOpen(true)}>
          Delete repository
        </Button>
      </section>

      <Modal open={deleteOpen} onOpenChange={setDeleteOpen} title="Delete repository">
        <label className="block font-mono text-[10.5px] text-text-tertiary" htmlFor="settings-confirm-delete">
          Type <span className="text-text-primary">{repository.name}</span> to confirm
        </label>
        <BoxedInput id="settings-confirm-delete" value={confirmText} onChange={(e) => setConfirmText(e.target.value)} className="mt-2" />
        <div className="mt-4 flex justify-end gap-3">
          <Button variant="ghost" onClick={() => setDeleteOpen(false)}>
            Cancel
          </Button>
          <Button
            variant="danger"
            disabled={confirmText !== repository.name}
            loading={deleteRepo.isPending}
            onClick={() => deleteRepo.mutate(repositoryId, { onSuccess: () => router.push("/") })}
          >
            Delete repository
          </Button>
        </div>
      </Modal>
    </div>
  );
}
