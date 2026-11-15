"""Auth request/response DTOs — validation only, no business logic."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class GuestCreateRequest(BaseModel):
    """Payload for ``POST /auth/guest``."""

    turnstile_token: Optional[str] = Field(None, max_length=4096, description="Cloudflare Turnstile response token.")


class RefreshRequest(BaseModel):
    """Payload for ``POST /auth/refresh``."""

    refresh_token: str = Field(..., min_length=20, max_length=512)


class LogoutRequest(BaseModel):
    """Payload for ``POST /auth/logout``."""

    refresh_token: str = Field(..., min_length=20, max_length=512)


class GitHubLoginRequest(BaseModel):
    """Payload for ``POST /auth/github``."""

    code: str = Field(..., min_length=1, max_length=512)
    state: str = Field(..., min_length=1, max_length=512)


class TokenPair(BaseModel):
    """An access/refresh token pair."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str


class UserResponse(BaseModel):
    """The caller's own identity."""

    id: uuid.UUID
    kind: str
    github_login: Optional[str]
    display_name: Optional[str]
    avatar_url: Optional[str]
    is_admin: bool
    guest_expires_at: Optional[datetime]


class QuotaStatus(BaseModel):
    """What the caller has used of their current limits."""

    repositories_used: int
    repositories_limit: int
    questions_used_today: int
    questions_limit_daily: int


class AuthSessionData(BaseModel):
    """Result of creating or refreshing a session."""

    tokens: TokenPair
    user: UserResponse
    quota: QuotaStatus


class GitHubLoginData(AuthSessionData):
    """Result of a GitHub login, including what happened to a guest's repositories."""

    repositories_transferred: int = 0


class GitHubAuthorizeData(BaseModel):
    """Where to send the browser to start GitHub login."""

    authorize_url: str
    state: str


class MeData(BaseModel):
    """Payload for ``GET /auth/me``."""

    user: UserResponse
    quota: QuotaStatus


class CleanupResult(BaseModel):
    """Payload for the internal guest-cleanup endpoint."""

    guests_deleted: int
    repositories_deleted: int
    guests_failed: int
