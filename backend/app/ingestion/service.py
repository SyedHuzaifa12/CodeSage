"""Workspace lifecycle service — file walk and metadata, never parsing.

Owns the workspace scan/refresh/reset lifecycle and the placeholder
indexing-trigger endpoint. Never reads file contents, never invokes
Tree-sitter, never generates embeddings — that begins in Sprint 2
(CLAUDE.md §6: "Ingestion module: file walk, Tree-sitter parsing,
symbol/import extraction"; this sprint implements file walk only).

Depends one-directionally on the Repository module's data-access layer
and exceptions to read repository facts — matching CLAUDE.md §3's
documented data flow (Repository → Files). It never writes to
repository-owned fields.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.ingestion import repository as ingestion_db
from app.ingestion.exceptions import RepositoryNotReadyError, WorkspaceNotFoundError, WorkspaceScanError
from app.ingestion.utils import scan_directory
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
        await ingestion_db.save_workspace(self._session, workspace)
        logger.info(
            "Workspace %s transitioned to READY for repository %s (%d files, %d folders)",
            workspace.id, repository_id, scan_result.total_files, scan_result.folder_count,
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
        """Clear a repository's workspace processing state without touching the clone.

        Removes all scanned file metadata and resets workspace statistics
        back to ``pending``. The cloned repository on disk is untouched.

        Args:
            repository_id: The repository's UUID.

        Returns:
            The reset workspace row.

        Raises:
            WorkspaceNotFoundError: If the repository has never been scanned.
        """
        workspace = await self.get_workspace(repository_id)
        await ingestion_db.replace_files(self._session, repository_id, [])

        workspace.status = "pending"
        workspace.progress = 0
        workspace.error_message = None
        workspace.total_files = 0
        workspace.supported_files = 0
        workspace.ignored_files = 0
        workspace.folder_count = 0
        workspace.repository_size_bytes = 0
        workspace.language_distribution = {}
        await ingestion_db.save_workspace(self._session, workspace)
        logger.info("Workspace %s reset to PENDING for repository %s", workspace.id, repository_id)
        return workspace

    async def request_indexing(self, repository_id: uuid.UUID) -> RepositoryWorkspace:
        """Validate a repository is ready and acknowledge an indexing request.

        Placeholder for Sprint 2 — performs no actual indexing, parsing,
        embedding, or AI work.

        Args:
            repository_id: The repository's UUID.

        Returns:
            The current workspace row, unchanged.

        Raises:
            RepositoryNotFoundError: If no repository has that id.
            RepositoryNotReadyError: If the repository is not cloned.
            WorkspaceNotFoundError: If the repository has not been scanned.
        """
        repository = await self._get_repository(repository_id)
        if repository.status != "ready":
            raise RepositoryNotReadyError(
                f"Repository '{repository_id}' is not ready for indexing (status={repository.status})."
            )
        workspace = await self.get_workspace(repository_id)
        logger.info("Indexing requested for repository %s (placeholder — implemented in Sprint 2)", repository_id)
        return workspace


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
