"""Auth-specific exceptions and their HTTP mapping (ADR-027).

Every error carries a stable machine-readable ``code`` so the frontend
can branch on it (e.g. show the sign-in prompt on ``GUEST_QUOTA_EXCEEDED``)
instead of parsing messages. Codes are delivered inside the standard
error envelope: ``errors: [{"code": "...", "detail": "..."}]``.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.exceptions.handlers import build_error_response

logger = logging.getLogger("codesage.auth.exceptions")


class AuthError(Exception):
    """Base class for all auth-module errors."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "AUTH_ERROR"


class UnauthenticatedError(AuthError):
    """No valid credentials were presented."""

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHENTICATED"


class RefreshTokenReuseError(UnauthenticatedError):
    """A rotated refresh token was replayed; its whole family was revoked."""

    code = "TOKEN_REUSED"


class ForbiddenError(AuthError):
    """The caller is authenticated but not allowed to do this."""

    status_code = status.HTTP_403_FORBIDDEN
    code = "FORBIDDEN"


class GuestQuotaExceededError(AuthError):
    """A guest hit a limit that signing in would lift."""

    status_code = status.HTTP_403_FORBIDDEN
    code = "GUEST_QUOTA_EXCEEDED"


class RateLimitedError(AuthError):
    """A rate or daily limit was hit."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "RATE_LIMITED"


class TurnstileVerificationError(AuthError):
    """The bot-protection challenge failed or was missing."""

    code = "TURNSTILE_FAILED"


class ServiceUnavailableError(AuthError):
    """A required dependency (Turnstile, GitHub, Redis) is unavailable or unconfigured."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "SERVICE_UNAVAILABLE"


class OAuthError(AuthError):
    """The GitHub login flow failed (bad/expired state, rejected code, ...)."""

    code = "OAUTH_FAILED"


async def auth_error_handler(request: Request, exc: AuthError) -> JSONResponse:
    """Translate an auth exception into the standard error envelope.

    Args:
        request: The incoming request.
        exc: The raised auth exception.

    Returns:
        A JSON response with the exception's status and a machine-readable code.
    """
    logger.warning("Auth error %s on %s %s: %s", exc.code, request.method, request.url.path, exc)
    response = build_error_response(exc.status_code, str(exc), [{"code": exc.code, "detail": str(exc)}])
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        response.headers["WWW-Authenticate"] = "Bearer"
    return response


def register_auth_exception_handlers(app: FastAPI) -> None:
    """Register the auth module's exception handler.

    Args:
        app: The FastAPI application instance.
    """
    app.add_exception_handler(AuthError, auth_error_handler)
