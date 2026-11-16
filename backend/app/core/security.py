"""Token primitives for authentication (ADR-027).

Pure functions only — no database, no FastAPI. The request-time
dependencies that *use* these (``get_current_user`` and friends) live in
``app.auth.dependencies``, which is allowed to touch the database; this
module is kept free of that so it stays trivially unit-testable.

Access tokens are short-lived HS256 JWTs. Refresh tokens are opaque
random strings; only their SHA-256 hash is ever persisted.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

from app.core.config import AuthSettings

_ALGORITHM = "HS256"


class AccessTokenError(Exception):
    """Raised when an access token is missing, malformed, tampered with, or expired."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class AccessTokenClaims:
    """The verified contents of an access token."""

    user_id: uuid.UUID
    kind: str
    jti: str
    expires_at: datetime


def create_access_token(
    user_id: uuid.UUID, kind: str, settings: AuthSettings, now: Optional[datetime] = None
) -> tuple[str, int]:
    """Mint a signed access token.

    Args:
        user_id: The authenticated user's id (becomes ``sub``).
        kind: ``"guest"`` or ``"user"`` — informational only; authorization
            always re-reads the kind from the database.
        settings: Auth settings (secret, issuer, lifetime).
        now: Override for the current time (tests).

    Returns:
        ``(token, expires_in_seconds)``.
    """
    issued_at = now or datetime.now(timezone.utc)
    lifetime = timedelta(minutes=settings.access_token_ttl_minutes)
    payload = {
        "sub": str(user_id),
        "kind": kind,
        "jti": uuid.uuid4().hex,
        "iss": settings.jwt_issuer,
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + lifetime).timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=_ALGORITHM)
    return token, int(lifetime.total_seconds())


def decode_access_token(token: str, settings: AuthSettings) -> AccessTokenClaims:
    """Verify an access token's signature, issuer, and expiry.

    Args:
        token: The raw bearer token.
        settings: Auth settings (secret, issuer).

    Returns:
        The verified claims.

    Raises:
        AccessTokenError: With reason ``"expired"`` or ``"invalid"``.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[_ALGORITHM],  # pinned: never trust the token's own "alg" header
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "exp", "iat", "iss", "jti"]},
        )
        return AccessTokenClaims(
            user_id=uuid.UUID(payload["sub"]),
            kind=str(payload.get("kind", "")),
            jti=str(payload["jti"]),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
        )
    except jwt.ExpiredSignatureError as exc:
        raise AccessTokenError("expired") from exc
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise AccessTokenError("invalid") from exc


def generate_refresh_token() -> str:
    """Return a new opaque refresh token (384 bits of randomness, URL-safe)."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw_token: str) -> str:
    """Return the hex SHA-256 digest used to store and look up a refresh token."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def constant_time_equals(left: str, right: str) -> bool:
    """Compare two secrets without leaking their common prefix length via timing."""
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
