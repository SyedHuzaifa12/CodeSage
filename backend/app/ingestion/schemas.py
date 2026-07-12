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
