"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { ErrorPanel } from "@/components/state/StateVocabulary";
import { useDeleteRepository } from "@/lib/query/repositories";
import type { Repository } from "@/lib/types/repository";

/** Typed-confirmation delete (Design System §14.2). Removes the local index only — never the GitHub source. */
export function DeleteRepositoryDialog({
  repository,
  onClose,
  onDeleted,
}: {
  repository: Repository | null;
  onClose: () => void;
  onDeleted?: (repo: Repository) => void;
}) {
  const [confirm, setConfirm] = useState("");
  const del = useDeleteRepository();
  useEffect(() => {
    setConfirm("");
    del.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset only when the target changes
  }, [repository?.id]);
  return (
    <Modal
      open={Boolean(repository)}
      onOpenChange={(open) => !open && onClose()}
      title="Delete repository"
      description={`This removes ${repository?.name ?? "this repository"}'s local index — metadata, vectors, cached data. The original GitHub source is never touched.`}
    >
      <label className="cs-mono-label block" htmlFor="cs-confirm-delete">
        Type <span className="normal-case tracking-normal text-text-primary">{repository?.name}</span> to confirm
      </label>
      <input
        id="cs-confirm-delete"
        value={confirm}
        onChange={(e) => setConfirm(e.target.value)}
        autoComplete="off"
        spellCheck={false}
        className="cs-underline-input mt-2 h-10 font-mono text-[13.5px]"
      />
      {del.isError && <ErrorPanel className="mt-3" error={del.error} />}
      <div className="mt-6 flex justify-end gap-2.5">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button
          variant="danger"
          disabled={!repository || confirm !== repository.name}
          loading={del.isPending}
          onClick={() =>
            repository &&
            del.mutate(repository.id, {
              onSuccess: () => {
                onDeleted?.(repository);
                onClose();
              },
            })
          }
        >
          Delete repository
        </Button>
      </div>
    </Modal>
  );
}
