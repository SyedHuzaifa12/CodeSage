"""Auth data-access layer — SQLAlchemy queries only, no business logic."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refresh_token import RefreshToken
from app.models.repository import Repository
from app.models.user import User


async def create_user(session: AsyncSession, user: User) -> User:
    """Persist a new user row and return it with database defaults loaded."""
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> Optional[User]:
    """Fetch a user by primary key."""
    return await session.get(User, user_id)


async def get_user_by_github_id(session: AsyncSession, github_id: int) -> Optional[User]:
    """Fetch the member linked to a GitHub account id, if any."""
    result = await session.execute(select(User).where(User.github_id == github_id))
    return result.scalar_one_or_none()


async def save_user(session: AsyncSession, user: User) -> User:
    """Flush and refresh a tracked user after in-place edits."""
    await session.flush()
    await session.refresh(user)
    return user


async def delete_user(session: AsyncSession, user: User) -> None:
    """Delete a user row (refresh tokens cascade; owned repositories must already be gone)."""
    await session.delete(user)
    await session.flush()


async def list_expired_guests(session: AsyncSession, now: datetime, limit: int) -> list[User]:
    """Guests whose expiry has passed, oldest first."""
    result = await session.execute(
        select(User)
        .where(User.kind == "guest", User.guest_expires_at.is_not(None), User.guest_expires_at <= now)
        .order_by(User.guest_expires_at)
        .limit(limit)
    )
    return list(result.scalars().all())


async def create_refresh_token(session: AsyncSession, token: RefreshToken) -> RefreshToken:
    """Persist a new refresh-token row."""
    session.add(token)
    await session.flush()
    return token


async def get_refresh_token_for_update(session: AsyncSession, token_hash: str) -> Optional[RefreshToken]:
    """Fetch a refresh token by hash, locking its row so concurrent refreshes serialize."""
    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
    )
    return result.scalar_one_or_none()


async def revoke_family(session: AsyncSession, family_id: uuid.UUID, now: datetime) -> None:
    """Revoke every still-active token in a family."""
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )


async def revoke_user_tokens(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> None:
    """Revoke every still-active refresh token a user holds."""
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )


async def count_active_repositories(session: AsyncSession, owner_id: uuid.UUID) -> int:
    """Repositories that count against a quota: owned, not demo, and not failed."""
    result = await session.execute(
        select(func.count())
        .select_from(Repository)
        .where(Repository.owner_id == owner_id, Repository.is_demo.is_(False), Repository.status != "failed")
    )
    return int(result.scalar_one())


async def list_owned_repository_ids(session: AsyncSession, owner_id: uuid.UUID) -> list[uuid.UUID]:
    """Ids of every repository a user owns, oldest first."""
    result = await session.execute(
        select(Repository.id).where(Repository.owner_id == owner_id).order_by(Repository.created_at)
    )
    return list(result.scalars().all())


async def reassign_repositories(
    session: AsyncSession, from_owner: uuid.UUID, to_owner: uuid.UUID, limit: int
) -> int:
    """Move up to ``limit`` of one user's repositories (oldest first) to another user.

    Returns:
        How many repositories were moved.
    """
    if limit <= 0:
        return 0
    ids = (await list_owned_repository_ids(session, from_owner))[:limit]
    if not ids:
        return 0
    await session.execute(update(Repository).where(Repository.id.in_(ids)).values(owner_id=to_owner))
    return len(ids)
