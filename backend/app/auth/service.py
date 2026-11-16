"""Auth business logic (ADR-027): sessions, rotation, GitHub login, guest cleanup."""
from __future__ import annotations

import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

import redis.asyncio as redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import repository as auth_db
from app.auth.exceptions import (
    OAuthError,
    RefreshTokenReuseError,
    ServiceUnavailableError,
    UnauthenticatedError,
)
from app.auth.github import GitHubOAuthClient, GitHubProfile
from app.auth.quota import QuotaService
from app.auth.schemas import QuotaStatus
from app.auth.turnstile import TurnstileVerifier
from app.auth.utils import utc_now
from app.core.config import Settings
from app.core.security import create_access_token, generate_refresh_token, hash_refresh_token
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.repository.service import RepositoryService

logger = logging.getLogger("codesage.auth.service")

_OAUTH_STATE_PREFIX = "codesage:oauth-state:"


@dataclass(frozen=True)
class IssuedSession:
    """A freshly minted token pair and the user it belongs to."""

    user: User
    access_token: str
    expires_in: int
    refresh_token: str
    refresh_token_id: uuid.UUID


@dataclass(frozen=True)
class GitHubLoginResult:
    """A session plus how many of a guest's repositories moved into the account."""

    session: IssuedSession
    repositories_transferred: int


@dataclass(frozen=True)
class CleanupSummary:
    """Outcome of one guest-cleanup pass."""

    guests_deleted: int
    repositories_deleted: int
    guests_failed: int


class AuthService:
    """Creates guests, rotates sessions, links GitHub identities, and purges expired guests."""

    def __init__(
        self,
        session: AsyncSession,
        redis_client: redis.Redis,
        settings: Settings,
        quota: QuotaService,
        turnstile: TurnstileVerifier,
        github: GitHubOAuthClient,
        repository_service: RepositoryService,
    ) -> None:
        self._session = session
        self._redis = redis_client
        self._settings = settings
        self._quota = quota
        self._turnstile = turnstile
        self._github = github
        self._repository_service = repository_service

    # ------------------------------------------------------------------ sessions

    async def create_guest(self, turnstile_token: Optional[str], client_ip: Optional[str]) -> IssuedSession:
        """Create a guest identity after rate-limiting and bot-checking the caller.

        Args:
            turnstile_token: The Turnstile widget token.
            client_ip: The caller's IP (rate-limit bucket and Turnstile signal).

        Returns:
            A session for the new guest.
        """
        await self._quota.check_guest_creation(client_ip)
        await self._turnstile.verify(turnstile_token, client_ip)

        now = utc_now()
        guest = User(
            id=uuid.uuid4(),
            kind="guest",
            last_seen_at=now,
            guest_expires_at=now + timedelta(hours=self._settings.auth.guest_ttl_hours),
        )
        guest = await auth_db.create_user(self._session, guest)
        logger.info("Guest %s created (expires %s)", guest.id, guest.guest_expires_at)
        return await self._issue_session(guest)

    async def refresh(self, raw_refresh_token: str) -> IssuedSession:
        """Rotate a refresh token: retire it and issue a new pair in the same family.

        Re-presenting an already-rotated token revokes the whole family
        (stolen-token detection) — except within a short grace window,
        which is treated as a harmless double-submit.

        Args:
            raw_refresh_token: The refresh token the client holds.

        Returns:
            A new session for the token's owner.

        Raises:
            UnauthenticatedError: Unknown, expired, or just-rotated token, or the owner is gone.
            RefreshTokenReuseError: A stale token was replayed and its family was revoked.
        """
        row = await auth_db.get_refresh_token_for_update(self._session, hash_refresh_token(raw_refresh_token))
        if row is None:
            raise UnauthenticatedError("Invalid refresh token.")

        now = utc_now()
        if row.revoked_at is not None:
            within_grace = (
                row.replaced_by is not None
                and (now - row.revoked_at).total_seconds() <= self._settings.auth.refresh_reuse_grace_seconds
            )
            if within_grace:
                raise UnauthenticatedError("Refresh token was just rotated; use the newest token.")
            await auth_db.revoke_family(self._session, row.family_id, now)
            # Committed before raising: get_db() rolls back on exceptions, which
            # would otherwise silently undo the revocation we just decided on.
            await self._session.commit()
            logger.warning("Refresh token reuse detected for user %s; family %s revoked", row.user_id, row.family_id)
            raise RefreshTokenReuseError("This session is no longer valid. Please sign in again.")

        if row.expires_at <= now:
            raise UnauthenticatedError("Refresh token expired.")

        user = await auth_db.get_user(self._session, row.user_id)
        if user is None or self._guest_expired(user, now):
            raise UnauthenticatedError("Session expired.")

        issued = await self._issue_session(user, family_id=row.family_id)
        row.revoked_at = now
        row.replaced_by = issued.refresh_token_id
        user.last_seen_at = now
        await self._session.flush()
        return issued

    async def logout(self, raw_refresh_token: str) -> None:
        """Revoke the whole token family behind a refresh token (idempotent)."""
        row = await auth_db.get_refresh_token_for_update(self._session, hash_refresh_token(raw_refresh_token))
        if row is not None:
            await auth_db.revoke_family(self._session, row.family_id, utc_now())

    # ------------------------------------------------------------------ GitHub

    async def github_authorize(self) -> tuple[str, str]:
        """Create a single-use CSRF state and the GitHub URL that carries it.

        Returns:
            ``(authorize_url, state)``.
        """
        state = secrets.token_urlsafe(32)
        url = self._github.build_authorize_url(state)
        try:
            await self._redis.set(
                f"{_OAUTH_STATE_PREFIX}{state}", "1", ex=self._settings.auth.oauth_state_ttl_seconds
            )
        except RedisError as exc:
            logger.exception("Could not store OAuth state")
            raise ServiceUnavailableError("Login is temporarily unavailable; please retry.") from exc
        return url, state

    async def github_login(self, code: str, state: str, current_user: Optional[User]) -> GitHubLoginResult:
        """Complete GitHub login, linking or upgrading the right account.

        Three outcomes:

        * the GitHub account already has a member -> sign into it; if the
          caller holds a guest session, move the guest's repositories
          across (up to the member's remaining capacity);
        * no member yet but the caller is a guest -> **upgrade the guest in
          place**, so their repository simply stays theirs;
        * neither -> create a fresh member.

        Args:
            code: The one-time code from GitHub's redirect.
            state: The CSRF state from the redirect; consumed here.
            current_user: The caller's current session, if any.

        Returns:
            The new session and how many guest repositories were transferred.

        Raises:
            OAuthError: Bad/expired state or a rejected code.
        """
        await self._consume_oauth_state(state)
        profile = await self._github.fetch_profile_for_code(code)

        # Re-read in *this* session rather than trusting the caller's object:
        # it may be attached to a different (or closed) session.
        guest = None
        if current_user is not None and current_user.kind == "guest":
            guest = await auth_db.get_user(self._session, current_user.id)
        now = utc_now()
        transferred = 0

        existing = await auth_db.get_user_by_github_id(self._session, profile.id)
        if existing is not None:
            if guest is not None and guest.id != existing.id:
                capacity = max(
                    0,
                    self._settings.auth.user_max_repositories
                    - await auth_db.count_active_repositories(self._session, existing.id),
                )
                transferred = await auth_db.reassign_repositories(self._session, guest.id, existing.id, capacity)
                await auth_db.revoke_user_tokens(self._session, guest.id, now)
            user = self._apply_profile(existing, profile)
        elif guest is not None:
            await auth_db.revoke_user_tokens(self._session, guest.id, now)
            guest.kind = "user"
            guest.guest_expires_at = None
            user = self._apply_profile(guest, profile)
            logger.info("Guest %s upgraded to member @%s", guest.id, profile.login)
        else:
            user = await auth_db.create_user(self._session, self._apply_profile(User(id=uuid.uuid4(), kind="user"), profile))

        user.last_seen_at = now
        user = await auth_db.save_user(self._session, user)
        issued = await self._issue_session(user)
        return GitHubLoginResult(session=issued, repositories_transferred=transferred)

    async def quota_status(self, user: User) -> QuotaStatus:
        """Summarise what the user has used of their repository and question limits."""
        return QuotaStatus(
            repositories_used=await auth_db.count_active_repositories(self._session, user.id),
            repositories_limit=self._quota.repository_limit(user),
            questions_used_today=await self._quota.questions_used_today(user),
            questions_limit_daily=self._quota.question_limit(user),
        )

    # ------------------------------------------------------------------ cleanup

    async def cleanup_expired_guests(self, limit: int = 25) -> CleanupSummary:
        """Delete expired guests together with everything they own.

        Each guest is handled in its own transaction so one failure never
        blocks the rest. Repositories go through the repository service so
        Qdrant vectors and the on-disk clone are removed too.

        Args:
            limit: Maximum guests to process in this pass.

        Returns:
            Counts of guests/repositories removed and guests that failed.
        """
        guests = await auth_db.list_expired_guests(self._session, utc_now(), limit)
        guests_deleted = repositories_deleted = guests_failed = 0
        for guest in guests:
            guest_id = guest.id
            try:
                for repository_id in await auth_db.list_owned_repository_ids(self._session, guest_id):
                    await self._repository_service.delete_repository(repository_id)
                    repositories_deleted += 1
                await auth_db.delete_user(self._session, guest)
                await self._session.commit()
                guests_deleted += 1
            except Exception:  # noqa: BLE001 -- one bad guest must not abort the pass; it is retried next run
                await self._session.rollback()
                guests_failed += 1
                logger.exception("Failed to clean up expired guest %s", guest_id)
        logger.info(
            "Guest cleanup: %d guests, %d repositories deleted, %d failed",
            guests_deleted, repositories_deleted, guests_failed,
        )
        return CleanupSummary(guests_deleted, repositories_deleted, guests_failed)

    # ------------------------------------------------------------------ internals

    @staticmethod
    def _guest_expired(user: User, now) -> bool:
        return user.kind == "guest" and user.guest_expires_at is not None and user.guest_expires_at <= now

    @staticmethod
    def _apply_profile(user: User, profile: GitHubProfile) -> User:
        user.github_id = profile.id
        user.github_login = profile.login
        user.display_name = profile.name or profile.login
        user.avatar_url = profile.avatar_url
        return user

    async def _consume_oauth_state(self, state: str) -> None:
        """Atomically read-and-delete the state so each one works exactly once."""
        try:
            stored = await self._redis.getdel(f"{_OAUTH_STATE_PREFIX}{state}")
        except RedisError as exc:
            logger.exception("Could not read OAuth state")
            raise ServiceUnavailableError("Login is temporarily unavailable; please retry.") from exc
        if stored is None:
            raise OAuthError("Login session expired or invalid. Please start signing in again.")

    async def _issue_session(self, user: User, family_id: Optional[uuid.UUID] = None) -> IssuedSession:
        """Mint an access token and persist a new refresh token for ``user``."""
        now = utc_now()
        days = (
            self._settings.auth.refresh_token_ttl_guest_days
            if user.kind == "guest"
            else self._settings.auth.refresh_token_ttl_user_days
        )
        expires_at = now + timedelta(days=days)
        if user.kind == "guest" and user.guest_expires_at is not None:
            expires_at = min(expires_at, user.guest_expires_at)

        raw = generate_refresh_token()
        token_id = uuid.uuid4()
        await auth_db.create_refresh_token(
            self._session,
            RefreshToken(
                id=token_id,
                user_id=user.id,
                family_id=family_id or uuid.uuid4(),
                token_hash=hash_refresh_token(raw),
                expires_at=expires_at,
            ),
        )
        access_token, expires_in = create_access_token(user.id, user.kind, self._settings.auth)
        return IssuedSession(
            user=user, access_token=access_token, expires_in=expires_in, refresh_token=raw, refresh_token_id=token_id
        )
