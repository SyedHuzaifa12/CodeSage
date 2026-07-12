"""Repository-specific exceptions and their HTTP mapping.

Domain exceptions are raised by ``service.py`` and translated here into
the standard error envelope (CLAUDE.md §14), keeping HTTP-status
knowledge out of the service layer and out of the route handlers.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.exceptions.handlers import build_error_response

logger = logging.getLogger("codesage.repository.exceptions")


class RepositoryError(Exception):
    """Base class for all repository-module errors."""


class InvalidRepositoryURLError(RepositoryError):
    """Raised when a supplied URL is not a valid GitHub repository URL."""


class RepositoryAlreadyExistsError(RepositoryError):
    """Raised when a repository with the same GitHub URL is already registered."""


class RepositoryNotFoundError(RepositoryError):
    """Raised when no repository matches the requested id."""


class RepositoryCloneError(RepositoryError):
    """Raised when GitPython fails to clone a repository."""


class RepositoryDeletionError(RepositoryError):
    """Raised when a repository's local clone cannot be removed from disk."""


_STATUS_BY_EXCEPTION: dict[type[RepositoryError], int] = {
    InvalidRepositoryURLError: status.HTTP_400_BAD_REQUEST,
    RepositoryAlreadyExistsError: status.HTTP_409_CONFLICT,
    RepositoryNotFoundError: status.HTTP_404_NOT_FOUND,
    RepositoryCloneError: status.HTTP_502_BAD_GATEWAY,
    RepositoryDeletionError: status.HTTP_500_INTERNAL_SERVER_ERROR,
}


async def repository_error_handler(request: Request, exc: RepositoryError) -> JSONResponse:
    """Translate a repository-domain exception into the standard error envelope.

    Args:
        request: The incoming request.
        exc: The raised repository exception.

    Returns:
        A JSON response using the module's status mapping, defaulting to 500
        for any ``RepositoryError`` subclass not explicitly mapped.
    """
    status_code = _STATUS_BY_EXCEPTION.get(type(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
    logger.warning("Repository error on %s %s: %s", request.method, request.url.path, exc)
    return build_error_response(status_code, str(exc), [{"detail": str(exc)}])


def register_repository_exception_handlers(app: FastAPI) -> None:
    """Register the repository module's exception handler.

    Args:
        app: The FastAPI application instance.
    """
    app.add_exception_handler(RepositoryError, repository_error_handler)
