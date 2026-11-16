"""Small, pure helpers shared across the auth module."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import Request

from app.core.config import AuthSettings
from app.models.user import User


def utc_now() -> datetime:
    """Return the current time as an aware UTC datetime."""
    return datetime.now(timezone.utc)


def is_admin(user: User, settings: AuthSettings) -> bool:
    """Whether the user is a member whose GitHub login is on the admin list.

    Args:
        user: The user to check.
        settings: Auth settings holding ``admin_github_logins``.

    Returns:
        ``True`` only for members (never guests) with a listed login.
    """
    return bool(user.kind == "user" and user.github_login and user.github_login.lower() in settings.admin_github_logins_list)


def client_ip(request: Request, settings: AuthSettings) -> Optional[str]:
    """Best-effort client IP for rate limiting.

    ``X-Forwarded-For`` is attacker-controlled unless trusted proxies
    wrote it, so it is only read when ``trusted_proxy_hops`` > 0. Each
    trusted proxy appends the address it saw, so the entry ``hops``
    positions from the end is the client as seen by the outermost trusted
    proxy; anything earlier was supplied by the client and is ignored.

    Args:
        request: The incoming request.
        settings: Auth settings.

    Returns:
        The client address, or ``None`` if it cannot be determined.
    """
    hops = settings.trusted_proxy_hops
    if hops > 0:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            entries = [entry.strip() for entry in forwarded.split(",") if entry.strip()]
            if len(entries) >= hops:
                return entries[-hops]
    return request.client.host if request.client else None
