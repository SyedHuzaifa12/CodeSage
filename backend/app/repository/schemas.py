"""Repository request/response DTOs — validation only, no business logic."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.repository.exceptions import InvalidRepositoryURLError
from app.repository.utils import parse_github_url


class RepositoryCreateRequest(BaseModel):
    """Payload for ``POST /repositories``."""

    github_url: str = Field(..., description="HTTPS GitHub repository URL.")
    name: Optional[str] = Field(None, min_length=1, max_length=255)

    @field_validator("github_url")
    @classmethod
    def _validate_github_url(cls, value: str) -> str:
        """Reject syntactically invalid GitHub URLs before hitting the service layer.

        Re-raises as ``ValueError`` (not the domain ``InvalidRepositoryURLError``)
        because Pydantic only guarantees ``ValueError``/``AssertionError`` raised
        inside a validator are caught and converted into a clean 422 response.
        """
        try:
            parse_github_url(value)
        except InvalidRepositoryURLError as exc:
            raise ValueError(str(exc)) from exc
        return value.strip()


class RepositoryUpdateRequest(BaseModel):
    """Payload for ``PATCH /repositories/{id}`` — only the display name is mutable."""

    name: str = Field(..., min_length=1, max_length=255)


class RepositoryResponse(BaseModel):
    """Serialized representation of a repository."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    github_url: Optional[str]
    local_path: str
    language: Optional[str]
    status: str
    indexing_status: str
    indexing_progress: int
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime


class RepositoryListData(BaseModel):
    """Payload shape for ``GET /repositories``."""

    repositories: list[RepositoryResponse]
    total: int
