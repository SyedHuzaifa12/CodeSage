"""Workspace lifecycle service — file walk and metadata, never parsing.

Owns the workspace scan/refresh/reset lifecycle and validates/triggers
indexing requests. Actual Tree-sitter parsing lives in
``parsing_service.py`` (Sprint 2A) — this service never reads file
contents or invokes Tree-sitter itself; it only flips
``Repository.indexing_status`` and hands off to the background task.

Depends one-directionally on the Repository module's data-access layer
and exceptions to read (and, for indexing status only, update)
repository facts — matching CLAUDE.md §3's documented data flow
(Repository → Files).
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.db.qdrant import get_qdrant_client
from app.ingestion import repository as ingestion_db
from app.ingestion.exceptions import (
    IndexingAlreadyInProgressError,
    NoIndexingInProgressError,
    RepositoryNotReadyError,
    WorkspaceNotFoundError,
    WorkspaceScanError,
)
from app.ingestion.utils import scan_directory
from app.knowledge import repository as knowledge_db
from app.knowledge.qdrant_store import delete_points_by_repository
from app.models.file import File
from app.models.repository import Repository
from app.models.repository_workspace import RepositoryWorkspace
from app.repository import repository as repository_db
from app.repository.exceptions import RepositoryNotFoundError

logger = logging.getLogger("codesage.ingestion.service")


class WorkspaceService:
    """Orchestrates workspace scanning, refresh, reset, and index-trigger."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the service.

        Args:
            session: The request-scoped database session.
        """
        self._session = session

    async def _get_repository(self, repository_id: uuid.UUID) -> Repository:
        """Fetch a repository or raise if it doesn't exist.

        Args:
            repository_id: The repository's UUID.

        Returns:
            The matching repository.

        Raises:
            RepositoryNotFoundError: If no repository has that id.
        """
        repository = await repository_db.get_by_id(self._session, repository_id)
        if repository is None:
            raise RepositoryNotFoundError(f"Repository '{repository_id}' was not found.")
        return repository

    async def scan_repository(self, repository_id: uuid.UUID) -> RepositoryWorkspace:
        """Perform (or re-perform) a full workspace scan for a repository.

        Args:
            repository_id: The repository to scan; must already be
                ``ready`` (cloned) with a valid local path.

        Returns:
            The resulting workspace row, in ``ready`` or ``failed`` status.

        Raises:
            RepositoryNotFoundError: If no repository has that id.
            RepositoryNotReadyError: If the repository has not finished cloning.
            WorkspaceScanError: If the local clone directory is missing or
                the scan otherwise fails.
        """
        repository = await self._get_repository(repository_id)
        if repository.status != "ready":
            raise RepositoryNotReadyError(
                f"Repository '{repository_id}' is not ready for scanning (status={repository.status})."
            )

        workspace = await ingestion_db.get_workspace(self._session, repository_id)
        if workspace is None:
            workspace = RepositoryWorkspace(repository_id=repository_id, status="pending")
            workspace = await ingestion_db.create_workspace(self._session, workspace)

        workspace.status = "scanning"
        workspace.progress = 0
        workspace.error_message = None
        await ingestion_db.save_workspace(self._session, workspace)
        logger.info("Workspace %s transitioning to SCANNING for repository %s", workspace.id, repository_id)

        local_path = Path(repository.local_path)
        if not local_path.exists():
            workspace.status = "failed"
            workspace.error_message = f"Local clone directory '{local_path}' does not exist."
            await ingestion_db.save_workspace(self._session, workspace)
            logger.error(
                "Workspace %s transitioned to FAILED for repository %s: local path missing",
                workspace.id, repository_id,
            )
            raise WorkspaceScanError(workspace.error_message)

        try:
            scan_result = scan_directory(local_path)
        except Exception as exc:
            workspace.status = "failed"
            workspace.error_message = str(exc)
            await ingestion_db.save_workspace(self._session, workspace)
            logger.error(
                "Workspace %s transitioned to FAILED for repository %s: %s", workspace.id, repository_id, exc
            )
            raise WorkspaceScanError(str(exc)) from exc

        file_rows = [
            File(
                repository_id=repository_id,
                path=scanned.path,
                language=scanned.language,
                size_bytes=scanned.size_bytes,
                last_modified=scanned.last_modified,
                is_hidden=scanned.is_hidden,
            )
            for scanned in scan_result.files
        ]
        await ingestion_db.replace_files(self._session, repository_id, file_rows)

        workspace.status = "ready"
        workspace.progress = 100
        workspace.total_files = scan_result.total_files
        workspace.supported_files = scan_result.supported_files
        workspace.ignored_files = scan_result.ignored_files
        workspace.folder_count = scan_result.folder_count
        workspace.repository_size_bytes = scan_result.repository_size_bytes
        workspace.language_distribution = scan_result.language_distribution
        workspace.excluded_files_count = scan_result.excluded_count
        workspace.excluded_by_reason = scan_result.excluded_by_reason
        workspace.excluded_samples = scan_result.excluded_samples
        await ingestion_db.save_workspace(self._session, workspace)
        logger.info(
            "Workspace %s transitioned to READY for repository %s (%d files, %d folders, "
            "%d excluded as noise: %s)",
            workspace.id, repository_id, scan_result.total_files, scan_result.folder_count,
            scan_result.excluded_count, scan_result.excluded_by_reason,
        )
        return workspace

    async def get_workspace(self, repository_id: uuid.UUID) -> RepositoryWorkspace:
        """Fetch a repository's workspace state.

        Args:
            repository_id: The repository's UUID.

        Returns:
            The workspace row.

        Raises:
            RepositoryNotFoundError: If no repository has that id.
            WorkspaceNotFoundError: If the repository exists but has never been scanned.
        """
        await self._get_repository(repository_id)
        workspace = await ingestion_db.get_workspace(self._session, repository_id)
        if workspace is None:
            raise WorkspaceNotFoundError(f"Repository '{repository_id}' has not been scanned yet.")
        return workspace

    async def get_tree(self, repository_id: uuid.UUID) -> list[File]:
        """Fetch every file for a repository, for building a nested tree view.

        Args:
            repository_id: The repository's UUID.

        Returns:
            All file rows for the repository.

        Raises:
            WorkspaceNotFoundError: If the repository has never been scanned.
        """
        await self.get_workspace(repository_id)
        return await ingestion_db.list_files(self._session, repository_id)

    async def refresh(self, repository_id: uuid.UUID) -> RepositoryWorkspace:
        """Re-scan a repository's workspace without re-cloning it.

        Args:
            repository_id: The repository's UUID.

        Returns:
            The updated workspace row.
        """
        logger.info("Refreshing workspace for repository %s", repository_id)
        return await self.scan_repository(repository_id)

    async def reset(self, repository_id: uuid.UUID) -> RepositoryWorkspace:
        """Clear all repository processing state without touching the clone.

        Removes scanned file metadata (which cascades to delete their
        symbols and knowledge chunks) and every parsed relationship, and
        resets both workspace (scan) and repository (index) state back
        to their initial values. The cloned repository on disk is
        untouched.

        Knowledge chunks are wiped in both stores: Postgres rows cascade
        automatically via ``files`` -> ``knowledge_chunks`` ``ON DELETE
        CASCADE``, but Qdrant has no such cascade, so its points are
        deleted explicitly here — otherwise a reset repository would
        keep serving stale vectors from before the reset.

        Args:
            repository_id: The repository's UUID.

        Returns:
            The reset workspace row.

        Raises:
            WorkspaceNotFoundError: If the repository has never been scanned.
        """
        workspace = await self.get_workspace(repository_id)
        await ingestion_db.replace_files(self._session, repository_id, [])
        await ingestion_db.replace_relationships(self._session, repository_id, [])
        await delete_points_by_repository(get_qdrant_client(), repository_id)

        workspace.status = "pending"
        workspace.progress = 0
        workspace.error_message = None
        workspace.total_files = 0
        workspace.supported_files = 0
        workspace.ignored_files = 0
        workspace.folder_count = 0
        workspace.repository_size_bytes = 0
        workspace.language_distribution = {}
        workspace.excluded_files_count = 0
        workspace.excluded_by_reason = {}
        workspace.excluded_samples = []
        await ingestion_db.save_workspace(self._session, workspace)

        repository = await self._get_repository(repository_id)
        repository.indexing_status = "not_started"
        repository.indexing_progress = 0
        repository.error_message = None
        await repository_db.save(self._session, repository)

        knowledge_state = await knowledge_db.get_index_state(self._session, repository_id)
        if knowledge_state is not None:
            knowledge_state.status = "pending"
            knowledge_state.progress = 0
            knowledge_state.error_message = None
            knowledge_state.total_files_considered = 0
            knowledge_state.total_files_skipped_unchanged = 0
            knowledge_state.total_files_failed = 0
            knowledge_state.total_chunks = 0
            knowledge_state.total_chunks_from_cache = 0
            knowledge_state.total_chunks_embedded_fresh = 0
            await knowledge_db.save_index_state(self._session, knowledge_state)

        logger.info("Workspace %s reset to PENDING for repository %s", workspace.id, repository_id)
        return workspace

    async def request_indexing(self, repository_id: uuid.UUID) -> RepositoryWorkspace:
        """Validate a repository is ready, flip it into the ``indexing`` state, and dispatch a Celery task.

        Validates and marks the repository as indexing, then dispatches
        ``app.ingestion.tasks.run_indexing_task`` (ADR-026) — the actual
        Tree-sitter parse/intelligence/knowledge pipeline runs in a
        Celery worker process, via its own fresh database session, not
        in this request or this process.

        This is a cheap, fast, user-facing rejection of the common case
        (the ``IndexingAlreadyInProgressError`` check below) — the real,
        race-free guarantee against two tasks running concurrently for
        the same repository is the Redis lock acquired by the task
        itself (``ingestion/indexing_lock.py``), which this check cannot
        fully replace: two near-simultaneous requests could both read
        ``indexing_status != "indexing"`` before either commits.

        Args:
            repository_id: The repository's UUID.

        Returns:
            The current workspace row (unchanged; indexing status lives
            on the repository, not the workspace).

        Raises:
            RepositoryNotFoundError: If no repository has that id.
            RepositoryNotReadyError: If the repository is not cloned.
            WorkspaceNotFoundError: If the repository has not been scanned.
            IndexingAlreadyInProgressError: If a previous indexing run for
                this repository is still in flight (duplicate-job
                prevention — see the exception's docstring).
        """
        repository = await self._get_repository(repository_id)
        if repository.status != "ready":
            raise RepositoryNotReadyError(
                f"Repository '{repository_id}' is not ready for indexing (status={repository.status})."
            )
        if repository.indexing_status == "indexing":
            raise IndexingAlreadyInProgressError(
                f"Repository '{repository_id}' is already indexing (progress={repository.indexing_progress}%); "
                "wait for it to finish or inspect GET /repositories/{id} before retrying."
            )
        workspace = await self.get_workspace(repository_id)

        repository.indexing_status = "indexing"
        repository.indexing_progress = 0
        repository.error_message = None
        await repository_db.save(self._session, repository)
        # Committed explicitly, here, rather than left to get_db()'s
        # end-of-request commit: the Celery task dispatched right after
        # this uses its OWN session and immediately writes to this same
        # row. If this request's transaction were still open (uncommitted)
        # when that write lands, the two sessions deadlock — this request
        # holds the row lock waiting for the task to finish, while the
        # task blocks waiting for the lock to clear.
        await self._session.commit()
        logger.info("Repository %s transitioning to INDEXING", repository_id)

        # Imported locally (not at module scope) to avoid Celery's own
        # configuration/import machinery running for every ordinary
        # request-handling import of this module — only paid when a
        # task is actually about to be dispatched.
        from app.ingestion.tasks import run_indexing_task

        async_result = run_indexing_task.delay(str(repository_id))
        repository.celery_task_id = async_result.id
        await repository_db.save(self._session, repository)
        await self._session.commit()
        logger.info("Repository %s indexing dispatched as Celery task %s", repository_id, async_result.id)

        return workspace

    async def cancel_indexing(self, repository_id: uuid.UUID) -> Repository:
        """Cancel an in-flight indexing run (ADR-026).

        Revokes the Celery task (``terminate=True`` — SIGTERM to the
        worker process currently executing it, since an indexing task
        has no cooperative cancellation checkpoint of its own to poll),
        proactively releases this repository's indexing lock rather than
        waiting out its TTL, and marks the repository ``failed`` with an
        explicit cancellation message so the frontend's existing
        ``indexing_status`` poll immediately reflects the outcome.

        Args:
            repository_id: The repository's UUID.

        Returns:
            The updated repository row.

        Raises:
            RepositoryNotFoundError: If no repository has that id.
            NoIndexingInProgressError: If no indexing run is currently in flight.
        """
        repository = await self._get_repository(repository_id)
        if repository.indexing_status != "indexing":
            raise NoIndexingInProgressError(
                f"Repository '{repository_id}' has no indexing run in progress (status={repository.indexing_status})."
            )

        # Imported locally — see the matching comment in
        # ``request_indexing`` for why.
        from app.core.celery_app import celery_app
        from app.db.redis import get_redis_client
        from app.ingestion.indexing_lock import lock_key_for

        if repository.celery_task_id:
            celery_app.control.revoke(repository.celery_task_id, terminate=True, signal="SIGTERM")
            logger.info("Revoked Celery task %s for repository %s", repository.celery_task_id, repository_id)

        # Best-effort: a terminated task's own `finally` may not run, so
        # this proactively clears the lock rather than leaving the
        # repository un-reindexable until the lock's TTL expires. Uses a
        # direct DELETE (not the compare-and-delete release helper) since
        # cancellation has no task-held token to compare against here.
        await get_redis_client().delete(lock_key_for(repository_id))

        repository.indexing_status = "failed"
        repository.error_message = "Indexing was cancelled by request."
        await repository_db.save(self._session, repository)
        await self._session.commit()
        logger.info("Repository %s indexing CANCELLED", repository_id)

        return repository


def get_workspace_service(session: AsyncSession = Depends(get_db)) -> WorkspaceService:
    """Build a request-scoped WorkspaceService for dependency injection.

    Colocated with the service (rather than in an api.py) so both the
    ingestion and repository modules' routers can share one canonical
    provider without importing across each other's api.py files.

    Args:
        session: Injected database session.

    Returns:
        A service instance bound to this request's session.
    """
    return WorkspaceService(session=session)
