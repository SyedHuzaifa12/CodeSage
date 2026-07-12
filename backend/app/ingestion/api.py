"""Repository Workspace REST API — routes only, no business logic (CLAUDE.md §10).

Nested under ``/repositories/{repository_id}/...`` since these are
actions on a repository resource, even though the underlying logic
lives in the Ingestion module (CLAUDE.md §6 — "file walk" is
Ingestion's job).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.ingestion.schemas import IndexTriggerResponse, RepositoryTreeData, WorkspaceResponse
from app.ingestion.service import WorkspaceService, get_workspace_service
from app.ingestion.utils import build_tree
from app.schemas.envelope import SuccessResponse

router = APIRouter(prefix="/repositories/{repository_id}", tags=["workspace"])


@router.get("/workspace", response_model=SuccessResponse[WorkspaceResponse])
async def get_workspace(
    repository_id: uuid.UUID,
    service: WorkspaceService = Depends(get_workspace_service),
) -> SuccessResponse[WorkspaceResponse]:
    """Fetch a repository's workspace scan status and statistics.

    Args:
        repository_id: The repository's UUID.
        service: Injected workspace service.

    Returns:
        The workspace's current state.
    """
    workspace = await service.get_workspace(repository_id)
    return SuccessResponse(message="Workspace retrieved.", data=workspace)


@router.get("/tree", response_model=SuccessResponse[RepositoryTreeData])
async def get_tree(
    repository_id: uuid.UUID,
    service: WorkspaceService = Depends(get_workspace_service),
) -> SuccessResponse[RepositoryTreeData]:
    """Fetch a repository's nested file/folder tree — no file contents.

    Args:
        repository_id: The repository's UUID.
        service: Injected workspace service.

    Returns:
        The repository's tree structure.
    """
    files = await service.get_tree(repository_id)
    tree = RepositoryTreeData(repository_id=repository_id, root=build_tree(files))
    return SuccessResponse(message="Repository tree retrieved.", data=tree)


@router.post("/refresh", response_model=SuccessResponse[WorkspaceResponse])
async def refresh_workspace(
    repository_id: uuid.UUID,
    service: WorkspaceService = Depends(get_workspace_service),
) -> SuccessResponse[WorkspaceResponse]:
    """Re-scan a repository's workspace without re-cloning it.

    Args:
        repository_id: The repository's UUID.
        service: Injected workspace service.

    Returns:
        The refreshed workspace state.
    """
    workspace = await service.refresh(repository_id)
    return SuccessResponse(message="Workspace refreshed.", data=workspace)


@router.post("/reset", response_model=SuccessResponse[WorkspaceResponse])
async def reset_workspace(
    repository_id: uuid.UUID,
    service: WorkspaceService = Depends(get_workspace_service),
) -> SuccessResponse[WorkspaceResponse]:
    """Clear a repository's workspace processing state without deleting the clone.

    Args:
        repository_id: The repository's UUID.
        service: Injected workspace service.

    Returns:
        The reset workspace state.
    """
    workspace = await service.reset(repository_id)
    return SuccessResponse(message="Workspace reset.", data=workspace)


@router.post(
    "/index",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SuccessResponse[IndexTriggerResponse],
)
async def trigger_indexing(
    repository_id: uuid.UUID,
    service: WorkspaceService = Depends(get_workspace_service),
) -> SuccessResponse[IndexTriggerResponse]:
    """Validate a repository and acknowledge an indexing request.

    Placeholder for Sprint 2 — performs no indexing, parsing, embedding,
    or AI work of any kind.

    Args:
        repository_id: The repository's UUID.
        service: Injected workspace service.

    Returns:
        An acknowledgement payload; no indexing has actually occurred.
    """
    workspace = await service.request_indexing(repository_id)
    data = IndexTriggerResponse(
        repository_id=repository_id,
        workspace_status=workspace.status,
        message="Indexing request accepted. Actual indexing is implemented in Sprint 2.",
    )
    return SuccessResponse(message="Indexing request accepted.", data=data)
