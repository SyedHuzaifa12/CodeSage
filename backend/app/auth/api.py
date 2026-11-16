"""Auth REST API — routes only, no business logic (CLAUDE.md §10)."""
from __future__ import annotations

from typing import Optional

import redis.asyncio as redis
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    get_current_user,
    get_optional_user,
    get_quota_service,
    require_internal_token,
)
from app.auth.github import GitHubOAuthClient
from app.auth.quota import QuotaService
from app.auth.schemas import (
    AuthSessionData,
    CleanupResult,
    GitHubAuthorizeData,
    GitHubLoginData,
    GitHubLoginRequest,
    GuestCreateRequest,
    LogoutRequest,
    MeData,
    QuotaStatus,
    RefreshRequest,
    TokenPair,
    UserResponse,
)
from app.auth.service import AuthService, IssuedSession
from app.auth.turnstile import TurnstileVerifier
from app.auth.utils import client_ip, is_admin
from app.core.config import Settings, get_settings
from app.db.postgres import get_db
from app.db.redis import get_redis
from app.models.user import User
from app.repository.api import get_repository_service
from app.repository.service import RepositoryService
from app.schemas.envelope import SuccessResponse

router = APIRouter(prefix="/auth", tags=["auth"])
internal_router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(require_internal_token)])


def get_auth_service(
    session: AsyncSession = Depends(get_db),
    client: redis.Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
    quota: QuotaService = Depends(get_quota_service),
    repository_service: RepositoryService = Depends(get_repository_service),
) -> AuthService:
    """Build a request-scoped :class:`AuthService`."""
    return AuthService(
        session=session,
        redis_client=client,
        settings=settings,
        quota=quota,
        turnstile=TurnstileVerifier(settings),
        github=GitHubOAuthClient(settings.auth),
        repository_service=repository_service,
    )


def _user_response(user: User, settings: Settings) -> UserResponse:
    return UserResponse(
        id=user.id,
        kind=user.kind,
        github_login=user.github_login,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        is_admin=is_admin(user, settings.auth),
        guest_expires_at=user.guest_expires_at,
    )


async def _quota_status(service: AuthService, user: User) -> QuotaStatus:
    return await service.quota_status(user)


async def _session_data(service: AuthService, issued: IssuedSession, settings: Settings) -> AuthSessionData:
    return AuthSessionData(
        tokens=TokenPair(
            access_token=issued.access_token, expires_in=issued.expires_in, refresh_token=issued.refresh_token
        ),
        user=_user_response(issued.user, settings),
        quota=await _quota_status(service, issued.user),
    )


@router.post("/guest", response_model=SuccessResponse[AuthSessionData])
async def create_guest(
    payload: GuestCreateRequest,
    request: Request,
    service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
) -> SuccessResponse[AuthSessionData]:
    """Start an anonymous guest session (bot-protected, rate-limited per IP).

    Args:
        payload: The Turnstile challenge token.
        request: The incoming request (for the caller's IP).
        service: Injected auth service.
        settings: Injected settings.

    Returns:
        Tokens and identity for the new guest, who may index one repository.
    """
    issued = await service.create_guest(payload.turnstile_token, client_ip(request, settings.auth))
    return SuccessResponse(message="Guest session created.", data=await _session_data(service, issued, settings))


@router.post("/refresh", response_model=SuccessResponse[AuthSessionData])
async def refresh_session(
    payload: RefreshRequest,
    service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
) -> SuccessResponse[AuthSessionData]:
    """Exchange a refresh token for a new access/refresh pair (the old one stops working).

    Args:
        payload: The refresh token currently held by the client.
        service: Injected auth service.
        settings: Injected settings.

    Returns:
        A rotated token pair.
    """
    issued = await service.refresh(payload.refresh_token)
    return SuccessResponse(message="Session refreshed.", data=await _session_data(service, issued, settings))


@router.post("/logout", response_model=SuccessResponse[dict])
async def logout(payload: LogoutRequest, service: AuthService = Depends(get_auth_service)) -> SuccessResponse[dict]:
    """Revoke the session behind a refresh token (idempotent).

    Args:
        payload: The refresh token to revoke.
        service: Injected auth service.

    Returns:
        An empty confirmation.
    """
    await service.logout(payload.refresh_token)
    return SuccessResponse(message="Signed out.", data={})


@router.get("/github/authorize", response_model=SuccessResponse[GitHubAuthorizeData])
async def github_authorize(service: AuthService = Depends(get_auth_service)) -> SuccessResponse[GitHubAuthorizeData]:
    """Begin GitHub login: returns the GitHub URL and the single-use CSRF state.

    Args:
        service: Injected auth service.

    Returns:
        ``authorize_url`` to redirect the browser to, and the ``state`` it carries.
    """
    url, state = await service.github_authorize()
    return SuccessResponse(message="GitHub authorization started.", data=GitHubAuthorizeData(authorize_url=url, state=state))


@router.post("/github", response_model=SuccessResponse[GitHubLoginData])
async def github_login(
    payload: GitHubLoginRequest,
    service: AuthService = Depends(get_auth_service),
    current_user: Optional[User] = Depends(get_optional_user),
    settings: Settings = Depends(get_settings),
) -> SuccessResponse[GitHubLoginData]:
    """Finish GitHub login. A guest bearer token, if sent, is upgraded in place (keeping their repository).

    Args:
        payload: The ``code`` and ``state`` GitHub redirected back with.
        service: Injected auth service.
        current_user: The caller's guest session, if they have one.
        settings: Injected settings.

    Returns:
        A member session, plus how many guest repositories were moved into the account.
    """
    result = await service.github_login(payload.code, payload.state, current_user)
    base = await _session_data(service, result.session, settings)
    data = GitHubLoginData(**base.model_dump(), repositories_transferred=result.repositories_transferred)
    return SuccessResponse(message="Signed in with GitHub.", data=data)


@router.get("/me", response_model=SuccessResponse[MeData])
async def me(
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
) -> SuccessResponse[MeData]:
    """Return the caller's identity and what they have used of their limits.

    Args:
        user: The authenticated caller.
        service: Injected auth service.
        settings: Injected settings.

    Returns:
        The user and their quota usage.
    """
    data = MeData(user=_user_response(user, settings), quota=await _quota_status(service, user))
    return SuccessResponse(message="Current user retrieved.", data=data)


@internal_router.post("/cleanup-guests", response_model=SuccessResponse[CleanupResult])
async def cleanup_guests(service: AuthService = Depends(get_auth_service)) -> SuccessResponse[CleanupResult]:
    """Delete expired guests and everything they own (server-to-server; needs ``X-Internal-Token``).

    Args:
        service: Injected auth service.

    Returns:
        How many guests and repositories were removed.
    """
    summary = await service.cleanup_expired_guests()
    data = CleanupResult(
        guests_deleted=summary.guests_deleted,
        repositories_deleted=summary.repositories_deleted,
        guests_failed=summary.guests_failed,
    )
    return SuccessResponse(message="Guest cleanup complete.", data=data)
