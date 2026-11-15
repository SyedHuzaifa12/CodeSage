"""FastAPI dependencies for authentication, ownership, and quotas (ADR-027).

The access policy for every repository-scoped route lives in
:func:`get_accessible_repository`:

* the owner may do anything;
* anyone signed in may *read* a demo repository, but only an admin may modify one;
* every other case answers **404**, identical to "does not exist", so a
  caller can never probe which repository ids are real.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Optional

import redis.asyncio as redis
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import repository as auth_db
from app.auth.exceptions import ForbiddenError, ServiceUnavailableError, UnauthenticatedError
from app.auth.quota import QuotaService
from app.auth.utils import is_admin, utc_now
from app.core.config import Settings, get_settings
from app.core.security import AccessTokenError, constant_time_equals, decode_access_token
from app.db.postgres import get_db
from app.db.redis import get_redis
from app.models.repository import Repository
from app.models.user import User
from app.repository import repository as repository_db
from app.repository.exceptions import RepositoryNotFoundError

logger = logging.getLogger("codesage.auth.dependencies")

_bearer_scheme = HTTPBearer(auto_error=False)


async def _resolve_user(
    credentials: Optional[HTTPAuthorizationCredentials], session: AsyncSession, settings: Settings
) -> Optional[User]:
    """Turn a bearer credential into a live user, or ``None`` if none was sent.

    Raises:
        UnauthenticatedError: A credential was sent but is invalid/expired, or its
            owner no longer exists or is an expired guest.
    """
    if credentials is None:
        return None
    try:
        claims = decode_access_token(credentials.credentials, settings.auth)
    except AccessTokenError as exc:
        message = "Access token expired." if exc.reason == "expired" else "Invalid access token."
        raise UnauthenticatedError(message) from exc

    user = await auth_db.get_user(session, claims.user_id)
    if user is None:
        raise UnauthenticatedError("Account no longer exists.")
    if user.kind == "guest" and user.guest_expires_at is not None and user.guest_expires_at <= utc_now():
        raise UnauthenticatedError("Guest session expired.")
    return user


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    """Require a valid bearer token and return its user."""
    user = await _resolve_user(credentials, session, settings)
    if user is None:
        raise UnauthenticatedError("Authentication required.")
    return user


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Optional[User]:
    """Return the caller's user if they sent a *usable* token, else ``None``.

    Deliberately lenient: a stale or malformed token is treated as "not
    signed in" rather than an error, so an expired guest token can never
    block someone from logging in.
    """
    try:
        return await _resolve_user(credentials, session, settings)
    except UnauthenticatedError:
        return None


async def require_admin(user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)) -> User:
    """Require a signed-in admin."""
    if not is_admin(user, settings.auth):
        raise ForbiddenError("Administrator access required.")
    return user


async def require_internal_token(request: Request, settings: Settings = Depends(get_settings)) -> None:
    """Guard server-to-server endpoints with the shared ``X-Internal-Token`` secret."""
    expected = settings.auth.internal_api_token
    if expected is None:
        raise ServiceUnavailableError("Internal endpoints are not enabled on this server.")
    presented = request.headers.get("x-internal-token", "")
    if not presented or not constant_time_equals(presented, expected.get_secret_value()):
        raise ForbiddenError("Invalid internal token.")


async def get_accessible_repository(
    repository_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> Repository:
    """Load a repository the caller may read, or raise 404.

    Used as a router-level dependency on every ``/repositories/{repository_id}/...``
    router, so no individual handler can forget the ownership check.
    """
    repository = await repository_db.get_by_id(session, repository_id)
    if repository is None or not (repository.owner_id == user.id or repository.is_demo):
        raise RepositoryNotFoundError(f"Repository '{repository_id}' was not found.")
    return repository


async def require_repository_write(
    repository: Repository = Depends(get_accessible_repository),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> Repository:
    """Like :func:`get_accessible_repository`, but also refuses to let non-admins modify a demo repository."""
    if repository.is_demo and not is_admin(user, settings.auth):
        raise ForbiddenError("The demo repository is read-only.")
    return repository


def ensure_report_regeneration_allowed(
    repository: Repository, user: User, settings: Settings, force_regenerate: bool
) -> None:
    """Stop non-admins from forcing a (costly) report rebuild on a shared demo repository."""
    if force_regenerate and repository.is_demo and not is_admin(user, settings.auth):
        raise ForbiddenError("The demo repository's reports are read-only.")


async def get_quota_service(
    client: redis.Redis = Depends(get_redis), settings: Settings = Depends(get_settings)
) -> QuotaService:
    """Build a request-scoped :class:`QuotaService`."""
    return QuotaService(client, settings.auth)


@dataclass(frozen=True)
class CreationLimits:
    """Size limits to apply while cloning a new repository (``None`` = unlimited)."""

    max_files: Optional[int]
    max_bytes: Optional[int]


class RepositoryCreationGuard:
    """Authorizes one repository creation for the current user.

    Exposed as an object the handler calls (rather than a plain
    dependency) so the quota check runs *after* the request body has
    validated — a malformed URL must not burn a guest's daily attempts.
    """

    def __init__(self, user: User, quota: QuotaService, session: AsyncSession, settings: Settings) -> None:
        self.user = user
        self._quota = quota
        self._session = session
        self._settings = settings

    async def authorize(self) -> CreationLimits:
        """Enforce repository quotas and return the clone limits for this user.

        Raises:
            GuestQuotaExceededError / RateLimitedError / ServiceUnavailableError: see
                :meth:`QuotaService.check_repository_creation`.
        """
        active = await auth_db.count_active_repositories(self._session, self.user.id)
        await self._quota.check_repository_creation(self.user, active)
        if self.user.kind == "guest":
            auth = self._settings.auth
            return CreationLimits(auth.guest_max_repository_files, auth.guest_max_repository_mb * 1024 * 1024)
        return CreationLimits(None, None)


async def get_repository_creation_guard(
    user: User = Depends(get_current_user),
    quota: QuotaService = Depends(get_quota_service),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RepositoryCreationGuard:
    """Build a request-scoped :class:`RepositoryCreationGuard`."""
    return RepositoryCreationGuard(user, quota, session, settings)


async def enforce_question_quota(
    user: User = Depends(get_current_user), quota: QuotaService = Depends(get_quota_service)
) -> None:
    """Count one LLM-backed request against the caller's daily question allowance."""
    await quota.consume_question(user)
