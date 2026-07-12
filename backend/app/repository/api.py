"""Repository REST API — routes only, no business logic (CLAUDE.md §10)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.postgres import get_db
from app.repository.schemas import (
    RepositoryCreateRequest,
    RepositoryListData,
    RepositoryResponse,
    RepositoryUpdateRequest,
)
from app.repository.service import RepositoryService
from app.schemas.envelope import SuccessResponse

router = APIRouter(prefix="/repositories", tags=["repositories"])


def get_repository_service(
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RepositoryService:
    """Build a request-scoped :class:`RepositoryService`.

    Args:
        session: Injected database session.
        settings: Injected application settings.

    Returns:
        A service instance bound to this request's session.
    """
    return RepositoryService(session=session, settings=settings)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=SuccessResponse[RepositoryResponse])
async def create_repository(
    payload: RepositoryCreateRequest,
    service: RepositoryService = Depends(get_repository_service),
) -> SuccessResponse[RepositoryResponse]:
    """Register and clone a new repository.

    Args:
        payload: The GitHub URL (and optional display name) to import.
        service: Injected repository service.

    Returns:
        The created repository.
    """
    repository = await service.create_repository(payload)
    return SuccessResponse(message="Repository imported.", data=repository)


@router.get("", response_model=SuccessResponse[RepositoryListData])
async def list_repositories(
    service: RepositoryService = Depends(get_repository_service),
) -> SuccessResponse[RepositoryListData]:
    """List every registered repository.

    Args:
        service: Injected repository service.

    Returns:
        Every repository and the total count.
    """
    repositories = await service.list_repositories()
    data = RepositoryListData(repositories=repositories, total=len(repositories))
    return SuccessResponse(message="Repositories retrieved.", data=data)


@router.get("/{repository_id}", response_model=SuccessResponse[RepositoryResponse])
async def get_repository(
    repository_id: uuid.UUID,
    service: RepositoryService = Depends(get_repository_service),
) -> SuccessResponse[RepositoryResponse]:
    """Fetch a single repository by id.

    Args:
        repository_id: The repository's UUID primary key.
        service: Injected repository service.

    Returns:
        The matching repository.
    """
    repository = await service.get_repository(repository_id)
    return SuccessResponse(message="Repository retrieved.", data=repository)


@router.patch("/{repository_id}", response_model=SuccessResponse[RepositoryResponse])
async def update_repository(
    repository_id: uuid.UUID,
    payload: RepositoryUpdateRequest,
    service: RepositoryService = Depends(get_repository_service),
) -> SuccessResponse[RepositoryResponse]:
    """Update a repository's mutable fields.

    Args:
        repository_id: The repository's UUID primary key.
        payload: The fields to update.
        service: Injected repository service.

    Returns:
        The updated repository.
    """
    repository = await service.update_repository(repository_id, payload)
    return SuccessResponse(message="Repository updated.", data=repository)


@router.delete("/{repository_id}", response_model=SuccessResponse[dict])
async def delete_repository(
    repository_id: uuid.UUID,
    service: RepositoryService = Depends(get_repository_service),
) -> SuccessResponse[dict]:
    """Delete a repository's local clone and metadata.

    Args:
        repository_id: The repository's UUID primary key.
        service: Injected repository service.

    Returns:
        A confirmation payload containing the deleted id. Never touches
        the original GitHub source — only the local index (CLAUDE.md §9).
    """
    await service.delete_repository(repository_id)
    return SuccessResponse(message="Repository deleted.", data={"id": str(repository_id)})
