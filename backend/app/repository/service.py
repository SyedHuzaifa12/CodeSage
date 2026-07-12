"""Repository lifecycle service — the only place status transitions happen.

Responsibilities: validate GitHub URLs, clone repositories locally,
persist/update metadata, update status, and delete local clones plus
metadata. Never parses source files, never generates embeddings, never
indexes — that is Ingestion's and Knowledge's job respectively
(CLAUDE.md §6).
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.repository import Repository
from app.repository import repository as repository_db
from app.repository.exceptions import RepositoryAlreadyExistsError, RepositoryNotFoundError
from app.repository.schemas import RepositoryCreateRequest, RepositoryUpdateRequest
from app.repository.utils import build_local_path, clone_repository, parse_github_url, remove_local_clone

logger = logging.getLogger("codesage.repository.service")


class RepositoryService:
    """Orchestrates the repository import/clone/update/delete lifecycle."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        """Initialize the service.

        Args:
            session: The request-scoped database session.
            settings: Application settings (used for the storage root path).
        """
        self._session = session
        self._settings = settings

    async def create_repository(self, payload: RepositoryCreateRequest) -> Repository:
        """Register a new repository and clone it locally.

        Args:
            payload: The validated creation request.

        Returns:
            The persisted repository, in ``ready`` or ``failed`` status.

        Raises:
            RepositoryAlreadyExistsError: If the URL is already registered.
            RepositoryCloneError: If cloning fails (also recorded on the row).
        """
        _, repo_name = parse_github_url(payload.github_url)

        existing = await repository_db.get_by_github_url(self._session, payload.github_url)
        if existing is not None:
            raise RepositoryAlreadyExistsError(f"Repository '{payload.github_url}' is already registered.")

        repository = Repository(
            name=payload.name or repo_name,
            github_url=payload.github_url,
            local_path="",
            status="pending",
        )
        repository = await repository_db.create(self._session, repository)
        logger.info("Repository %s created with status PENDING", repository.id)

        storage_root = Path(self._settings.app.repository_storage_path)
        local_path = build_local_path(storage_root, repository.id)
        repository.local_path = str(local_path)
        repository.status = "cloning"
        await repository_db.save(self._session, repository)
        logger.info("Repository %s transitioning to CLONING at %s", repository.id, local_path)

        try:
            clone_repository(payload.github_url, local_path)
        except Exception as exc:
            repository.status = "failed"
            repository.error_message = str(exc)
            await repository_db.save(self._session, repository)
            logger.error("Repository %s transitioned to FAILED: %s", repository.id, exc)
            raise

        repository.status = "ready"
        repository.error_message = None
        await repository_db.save(self._session, repository)
        logger.info("Repository %s transitioned to READY", repository.id)
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

    async def list_repositories(self) -> list[Repository]:
        """Fetch every registered repository.

        Returns:
            All repositories, most recently created first.
        """
        return await repository_db.list_all(self._session)

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
        row) is removed entirely, matching CLAUDE.md §9 — only the local
        index is affected, never the original GitHub source. ``DELETED``
        is set on the in-memory instance immediately beforehand purely so
        the transition is logged consistently; it is never persisted as a
        queryable state.

        Args:
            repository_id: The repository's UUID primary key.

        Raises:
            RepositoryNotFoundError: If no repository has that id.
        """
        repository = await self.get_repository(repository_id)
        repository.status = "deleted"
        logger.info("Repository %s transitioning to DELETED", repository.id)

        remove_local_clone(Path(repository.local_path))
        await repository_db.delete(self._session, repository)
        logger.info("Repository %s deleted", repository_id)
