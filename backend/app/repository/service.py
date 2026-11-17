"""Repository lifecycle service — the only place status transitions happen.

Responsibilities: validate GitHub URLs, clone repositories locally,
persist/update metadata, update status, and delete local clones plus
metadata. Never parses source files, never generates embeddings, never
indexes — that is Ingestion's and Knowledge's job respectively
(CLAUDE.md §6).
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.qdrant import get_qdrant_client
from app.indexing.notify import is_postgres_backend
from app.indexing.service import cancel_job
from app.ingestion.service import WorkspaceService
from app.knowledge.qdrant_store import delete_points_by_repository
from app.models.repository import Repository
from app.repository import repository as repository_db
from app.repository.exceptions import (
    RepositoryAlreadyExistsError,
    RepositoryNotFoundError,
    RepositoryTooLargeError,
)
from app.repository.schemas import RepositoryCreateRequest, RepositoryUpdateRequest
from app.repository.utils import (
    build_local_path,
    clone_repository,
    fetch_remote_size_kb,
    measure_tree,
    parse_github_url,
    remove_local_clone,
)

logger = logging.getLogger("codesage.repository.service")

_TOO_LARGE_MESSAGE = "This repository is larger than the free demo allows. Sign in with GitHub to index bigger repositories."
# GitHub's reported size includes the full git history, which a shallow clone does not download. A repository whose
# history is more than this many times the guest limit is refused up front; anything smaller is cloned and then measured.
_REMOTE_HISTORY_FACTOR = 12


class RepositoryService:
    """Orchestrates the repository import/clone/update/delete lifecycle."""

    def __init__(self, session: AsyncSession, settings: Settings, workspace_service: WorkspaceService) -> None:
        """Initialize the service.

        Args:
            session: The request-scoped database session.
            settings: Application settings (used for the storage root path).
            workspace_service: Used to trigger the initial workspace scan
                immediately after a successful clone (CLAUDE.md §3's
                documented Repository → Files data flow).
        """
        self._session = session
        self._settings = settings
        self._workspace_service = workspace_service

    async def register_repository(self, payload: RepositoryCreateRequest, owner_id: uuid.UUID) -> Repository:
        """Validate the URL and create the repository row, without cloning anything.

        Args:
            payload: The validated creation request.
            owner_id: The user who will own the repository.

        Returns:
            The persisted repository in ``cloning`` status, with its clone path assigned.

        Raises:
            RepositoryAlreadyExistsError: If this owner already imported the URL.
        """
        _, repo_name = parse_github_url(payload.github_url)

        existing = await repository_db.get_by_github_url(self._session, payload.github_url, owner_id)
        if existing is not None:
            raise RepositoryAlreadyExistsError(f"Repository '{payload.github_url}' is already registered.")

        repository = Repository(
            name=payload.name or repo_name,
            github_url=payload.github_url,
            local_path="",
            status="pending",
            owner_id=owner_id,
        )
        repository = await repository_db.create(self._session, repository)
        logger.info("Repository %s created with status PENDING", repository.id)

        storage_root = Path(self._settings.app.repository_storage_path)
        local_path = build_local_path(storage_root, repository.id)
        repository.local_path = str(local_path)
        repository.status = "cloning"
        await repository_db.save(self._session, repository)
        logger.info("Repository %s transitioning to CLONING at %s", repository.id, local_path)
        return repository

    async def clone_and_scan(
        self,
        repository: Repository,
        max_files: Optional[int] = None,
        max_bytes: Optional[int] = None,
        *,
        publish_progress: bool = False,
        begin_indexing: bool = False,
    ) -> None:
        """Clone a registered repository, enforce size limits, and run the first workspace scan.

        The blocking work (``git clone``, the size walk, the scan) runs in a worker
        thread so it never stalls the event loop of whichever process calls this.

        Args:
            repository: A repository returned by :meth:`register_repository`.
            max_files: If set, reject a clone containing more files than this.
            max_bytes: If set, reject a clone whose working tree exceeds this size.
            publish_progress: Commit after each status change so other processes polling the
                row see it immediately (the indexer needs this; a request handler does not).
            begin_indexing: Flip ``indexing_status`` to ``indexing`` in the same commit that
                marks the clone ready, so a poller never sees a "ready, not started" gap
                between cloning and the automatic indexing that follows it.

        Raises:
            RepositoryCloneError: If cloning fails (also recorded on the row).
            RepositoryTooLargeError: If the clone exceeds ``max_files``/``max_bytes``.
        """
        local_path = Path(repository.local_path)
        # A retried job may find a half-finished clone from the attempt that died.
        remove_local_clone(local_path)

        clone_started = time.perf_counter()
        try:
            if max_bytes is not None:
                # A guest's size cap used to be checked only after the whole repository had been downloaded, so a huge
                # one tied up the (single-job) indexer for as long as the download took. GitHub reports the size up front.
                remote_kb = await asyncio.to_thread(fetch_remote_size_kb, repository.github_url)
                if remote_kb is not None and remote_kb * 1024 > max_bytes * _REMOTE_HISTORY_FACTOR:
                    raise RepositoryTooLargeError(_TOO_LARGE_MESSAGE)
            await asyncio.to_thread(
                clone_repository, repository.github_url, local_path, self._settings.ingestion.clone_timeout_seconds
            )
            if max_files is not None or max_bytes is not None:
                measure = await asyncio.to_thread(measure_tree, local_path, max_files, max_bytes)
                if measure.exceeded:
                    remove_local_clone(local_path)
                    raise RepositoryTooLargeError(_TOO_LARGE_MESSAGE)
        except Exception as exc:
            repository.status = "failed"
            repository.error_message = str(exc)
            await repository_db.save(self._session, repository)
            if publish_progress:
                await self._session.commit()
            logger.error("Repository %s transitioned to FAILED: %s", repository.id, exc)
            raise
        clone_ms = int((time.perf_counter() - clone_started) * 1000)

        repository.status = "ready"
        repository.error_message = None
        if begin_indexing:
            repository.indexing_status = "indexing"
            repository.indexing_progress = 0
        await repository_db.save(self._session, repository)
        if publish_progress:
            await self._session.commit()
        logger.info("Repository %s transitioned to READY (clone_ms=%d)", repository.id, clone_ms)

        scan_started = time.perf_counter()
        excluded_count = 0
        try:
            workspace = await self._workspace_service.scan_repository(repository.id)
            excluded_count = workspace.excluded_files_count
        except Exception as exc:
            # A failed initial scan must not fail the clone itself — the
            # repository is genuinely ready; the workspace independently
            # records its own failed state, discoverable via its own endpoints.
            logger.error("Initial workspace scan failed for repository %s: %s", repository.id, exc)
        scan_ms = int((time.perf_counter() - scan_started) * 1000)
        logger.info(
            "STAGE_TIMING repository=%s clone_ms=%d scan_ms=%d excluded_files=%d",
            repository.id, clone_ms, scan_ms, excluded_count,
        )
        if publish_progress:
            await self._session.commit()

    async def create_repository(
        self,
        payload: RepositoryCreateRequest,
        owner_id: uuid.UUID,
        max_files: Optional[int] = None,
        max_bytes: Optional[int] = None,
    ) -> Repository:
        """Register a new repository for ``owner_id`` and clone it before returning.

        This is the inline path (``INDEXING_BACKEND=celery`` and scripts). In
        ``postgres`` mode the API only calls :meth:`register_repository` and leaves the
        clone to the indexer.

        Args:
            payload: The validated creation request.
            owner_id: The user who will own the repository.
            max_files: If set, reject a clone containing more files than this.
            max_bytes: If set, reject a clone whose working tree exceeds this size.

        Returns:
            The persisted repository, in ``ready`` or ``failed`` status.

        Raises:
            RepositoryAlreadyExistsError: If this owner already imported the URL.
            RepositoryCloneError: If cloning fails (also recorded on the row).
            RepositoryTooLargeError: If the clone exceeds ``max_files``/``max_bytes``.
        """
        repository = await self.register_repository(payload, owner_id)
        await self.clone_and_scan(repository, max_files, max_bytes)
        return repository

    async def get_repository(self, repository_id: uuid.UUID) -> Repository:
        """Fetch a single repository by id.

        Args:
            repository_id: The repository's UUID primary key.

        Returns:
            The matching repository.

        Raises:
            RepositoryNotFoundError: If no repository has that id.
        """
        repository = await repository_db.get_by_id(self._session, repository_id)
        if repository is None:
            raise RepositoryNotFoundError(f"Repository '{repository_id}' was not found.")
        return repository

    async def list_repositories(self, owner_id: uuid.UUID) -> list[Repository]:
        """Fetch the repositories a user may see: their own plus every demo repository.

        Args:
            owner_id: The viewing user.

        Returns:
            Visible repositories, most recently created first.
        """
        return await repository_db.list_visible(self._session, owner_id)

    async def update_repository(self, repository_id: uuid.UUID, payload: RepositoryUpdateRequest) -> Repository:
        """Update a repository's mutable fields (currently: display name only).

        Args:
            repository_id: The repository's UUID primary key.
            payload: The validated update request.

        Returns:
            The updated repository.

        Raises:
            RepositoryNotFoundError: If no repository has that id.
        """
        repository = await self.get_repository(repository_id)
        repository.name = payload.name
        await repository_db.save(self._session, repository)
        logger.info("Repository %s renamed to '%s'", repository.id, repository.name)
        return repository

    async def delete_repository(self, repository_id: uuid.UUID) -> None:
        """Remove a repository's local clone and all of its metadata.

        Performs a hard delete: the row (and, via cascade, every child
        row — including knowledge chunk metadata) is removed entirely,
        matching CLAUDE.md §9 — only the local index is affected, never
        the original GitHub source. ``DELETED`` is set on the in-memory
        instance immediately beforehand purely so the transition is
        logged consistently; it is never persisted as a queryable state.

        Qdrant has no foreign-key cascade, so this repository's vector
        points are deleted explicitly before the Postgres delete —
        otherwise they would silently outlive the repository they
        belong to and could be served as query results after deletion.

        Args:
            repository_id: The repository's UUID primary key.

        Raises:
            RepositoryNotFoundError: If no repository has that id.
        """
        repository = await self.get_repository(repository_id)
        if is_postgres_backend(self._settings):
            # Withdraw/stop any queued or running job first and make that visible, so the indexer stops at its
            # next stage boundary instead of indexing a repository that is about to disappear.
            await cancel_job(self._session, repository_id)
            await self._session.commit()
        repository.status = "deleted"
        logger.info("Repository %s transitioning to DELETED", repository.id)

        await delete_points_by_repository(get_qdrant_client(), repository_id)
        remove_local_clone(Path(repository.local_path))
        await repository_db.delete(self._session, repository)
        logger.info("Repository %s deleted", repository_id)
