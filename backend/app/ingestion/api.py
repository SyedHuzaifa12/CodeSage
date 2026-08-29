"""Repository Workspace REST API — routes only, no business logic (CLAUDE.md §10).

Nested under ``/repositories/{repository_id}/...`` since these are
actions on a repository resource, even though the underlying logic
lives in the Ingestion module (CLAUDE.md §6 — "file walk" is
Ingestion's job).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.ingestion.intelligence_service import RepositoryIntelligenceService
from app.ingestion.parsing_service import run_parsing_pipeline
from app.ingestion.schemas import (
    CallGraphData,
    DependencyGraphData,
    GraphEdge,
    IndexTriggerResponse,
    IntelligenceResponse,
    RepositoryTreeData,
    SymbolExplorerData,
    SymbolExplorerItem,
    WorkspaceResponse,
)
from app.ingestion.service import WorkspaceService, get_workspace_service
from app.ingestion.utils import build_tree
from app.schemas.envelope import SuccessResponse

router = APIRouter(prefix="/repositories/{repository_id}", tags=["workspace"])


def get_intelligence_service(session: AsyncSession = Depends(get_db)) -> RepositoryIntelligenceService:
    """Build a request-scoped RepositoryIntelligenceService for dependency injection.

    Args:
        session: Injected database session.

    Returns:
        A service instance bound to this request's session.
    """
    return RepositoryIntelligenceService(session=session)


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
    background_tasks: BackgroundTasks,
    service: WorkspaceService = Depends(get_workspace_service),
) -> SuccessResponse[IndexTriggerResponse]:
    """Validate a repository and start Tree-sitter parsing in the background.

    Per CLAUDE.md §6, indexing runs as a FastAPI ``BackgroundTask``: this
    request only validates the repository and flips it to ``indexing``;
    the actual parse (``parsing_service.run_parsing_pipeline``) runs
    after the response is sent, using its own fresh database session.

    Args:
        repository_id: The repository's UUID.
        background_tasks: FastAPI's background-task registrar.
        service: Injected workspace service.

    Returns:
        An acknowledgement payload — parsing has started, not finished;
        poll ``GET /repositories/{id}`` for ``indexing_status``/``indexing_progress``.
    """
    workspace = await service.request_indexing(repository_id)
    background_tasks.add_task(run_parsing_pipeline, repository_id)
    data = IndexTriggerResponse(
        repository_id=repository_id,
        workspace_status=workspace.status,
        message="Indexing started in the background. Poll GET /repositories/{id} for progress.",
    )
    return SuccessResponse(message="Indexing request accepted.", data=data)


@router.get("/intelligence", response_model=SuccessResponse[IntelligenceResponse])
async def get_intelligence(
    repository_id: uuid.UUID,
    service: RepositoryIntelligenceService = Depends(get_intelligence_service),
) -> SuccessResponse[IntelligenceResponse]:
    """Fetch a repository's statistics, dependency analysis, and rule-based summary.

    Args:
        repository_id: The repository's UUID.
        service: Injected intelligence service.

    Returns:
        The repository's intelligence row.
    """
    intelligence = await service.get_intelligence(repository_id)
    return SuccessResponse(message="Repository intelligence retrieved.", data=intelligence)


@router.get("/call-graph", response_model=SuccessResponse[CallGraphData])
async def get_call_graph(
    repository_id: uuid.UUID,
    service: RepositoryIntelligenceService = Depends(get_intelligence_service),
) -> SuccessResponse[CallGraphData]:
    """Fetch the resolved caller -> callee call graph.

    Args:
        repository_id: The repository's UUID.
        service: Injected intelligence service.

    Returns:
        Every resolved call edge, plus the set of symbols involved.
    """
    nodes, edges = await service.get_call_graph(repository_id)
    data = CallGraphData(
        repository_id=repository_id, nodes=nodes, edges=[GraphEdge(source=s, target=t) for s, t in edges]
    )
    return SuccessResponse(message="Call graph retrieved.", data=data)


@router.get("/dependency-graph", response_model=SuccessResponse[DependencyGraphData])
async def get_dependency_graph(
    repository_id: uuid.UUID,
    service: RepositoryIntelligenceService = Depends(get_intelligence_service),
) -> SuccessResponse[DependencyGraphData]:
    """Fetch the resolved import/dependency graph, circular dependencies, and orphan files.

    Args:
        repository_id: The repository's UUID.
        service: Injected intelligence service.

    Returns:
        Every resolved internal import edge plus dependency analysis results.
    """
    nodes, edges, cycles, orphans = await service.get_dependency_graph(repository_id)
    data = DependencyGraphData(
        repository_id=repository_id,
        nodes=nodes,
        edges=[GraphEdge(source=s, target=t) for s, t in edges],
        circular_dependencies=cycles,
        orphan_files=orphans,
    )
    return SuccessResponse(message="Dependency graph retrieved.", data=data)


@router.get("/symbols", response_model=SuccessResponse[SymbolExplorerData])
async def get_symbols(
    repository_id: uuid.UUID,
    service: RepositoryIntelligenceService = Depends(get_intelligence_service),
) -> SuccessResponse[SymbolExplorerData]:
    """Fetch every parsed symbol for a repository, joined with its file path.

    Args:
        repository_id: The repository's UUID.
        service: Injected intelligence service.

    Returns:
        Every symbol, for the Symbol Explorer DevTools page.
    """
    pairs = await service.get_symbols(repository_id)
    items = [
        SymbolExplorerItem(
            id=symbol.id,
            file_id=symbol.file_id,
            file_path=file_path,
            parent_symbol_id=symbol.parent_symbol_id,
            name=symbol.name,
            qualified_name=symbol.qualified_name,
            symbol_type=symbol.symbol_type,
            visibility=symbol.visibility,
            start_line=symbol.start_line,
            end_line=symbol.end_line,
            signature=symbol.signature,
        )
        for symbol, file_path in pairs
    ]
    data = SymbolExplorerData(repository_id=repository_id, symbols=items)
    return SuccessResponse(message="Symbols retrieved.", data=data)
