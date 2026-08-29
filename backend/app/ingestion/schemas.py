"""Ingestion/workspace request-response DTOs — validation only, no business logic."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class WorkspaceResponse(BaseModel):
    """Serialized workspace scan state and statistics."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    repository_id: uuid.UUID
    status: str
    progress: int
    error_message: Optional[str]
    total_files: int
    supported_files: int
    ignored_files: int
    folder_count: int
    repository_size_bytes: int
    language_distribution: dict[str, int]
    created_at: datetime
    updated_at: datetime


class TreeNode(BaseModel):
    """A single node (file or folder) in the nested repository tree."""

    name: str
    type: str
    path: str
    children: Optional[list["TreeNode"]] = None
    language: Optional[str] = None
    size_bytes: Optional[int] = None


TreeNode.model_rebuild()


class RepositoryTreeData(BaseModel):
    """Payload shape for ``GET /repositories/{id}/tree``."""

    repository_id: uuid.UUID
    root: list[TreeNode]


class IndexTriggerResponse(BaseModel):
    """Payload shape for ``POST /repositories/{id}/index`` (Sprint 1B placeholder)."""

    repository_id: uuid.UUID
    workspace_status: str
    message: str


class IntelligenceResponse(BaseModel):
    """Serialized repository intelligence — statistics, dependency analysis, and summary."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    repository_id: uuid.UUID
    status: str
    progress: int
    error_message: Optional[str]

    total_symbols: int
    total_classes: int
    total_interfaces: int
    total_enums: int
    total_functions: int
    total_methods: int
    total_variables: int
    total_namespaces: int
    total_imports: int
    total_calls: int
    inheritance_count: int
    dependency_count: int

    circular_dependencies: list[list[str]]
    orphan_files: list[str]

    languages: dict[str, int]
    architecture_hints: list[str]
    entry_points: list[str]
    largest_modules: list[dict]
    dependency_hotspots: list[dict]

    created_at: datetime
    updated_at: datetime


class GraphEdge(BaseModel):
    """A single directed edge in a call/dependency graph view."""

    source: str
    target: str


class CallGraphData(BaseModel):
    """Payload shape for ``GET /repositories/{id}/call-graph``."""

    repository_id: uuid.UUID
    nodes: list[str]
    edges: list[GraphEdge]


class DependencyGraphData(BaseModel):
    """Payload shape for ``GET /repositories/{id}/dependency-graph``."""

    repository_id: uuid.UUID
    nodes: list[str]
    edges: list[GraphEdge]
    circular_dependencies: list[list[str]]
    orphan_files: list[str]


class SymbolExplorerItem(BaseModel):
    """A single symbol row, joined with its owning file's path, for the Symbol Explorer."""

    id: uuid.UUID
    file_id: uuid.UUID
    file_path: str
    parent_symbol_id: Optional[uuid.UUID]
    name: str
    qualified_name: str
    symbol_type: str
    visibility: str
    start_line: int
    end_line: int
    signature: Optional[str]


class SymbolExplorerData(BaseModel):
    """Payload shape for ``GET /repositories/{id}/symbols``."""

    repository_id: uuid.UUID
    symbols: list[SymbolExplorerItem]
