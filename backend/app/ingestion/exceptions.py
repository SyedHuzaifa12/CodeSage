"""Ingestion (workspace) exceptions and their HTTP mapping.

Domain exceptions are raised by ``service.py`` and translated here into
the standard error envelope (CLAUDE.md §14).
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.exceptions.handlers import build_error_response

logger = logging.getLogger("codesage.ingestion.exceptions")


class IngestionError(Exception):
    """Base class for all ingestion-module errors."""


class RepositoryNotReadyError(IngestionError):
    """Raised when a workspace operation is requested before the repository has finished cloning."""


class WorkspaceNotFoundError(IngestionError):
    """Raised when a repository has never been scanned."""


class WorkspaceScanError(IngestionError):
    """Raised when a workspace scan fails (e.g. the local clone directory is missing)."""


class IntelligenceNotFoundError(IngestionError):
    """Raised when a repository exists but has never been analyzed (Sprint 2B)."""


_STATUS_BY_EXCEPTION: dict[type[IngestionError], int] = {
    RepositoryNotReadyError: status.HTTP_409_CONFLICT,
    WorkspaceNotFoundError: status.HTTP_404_NOT_FOUND,
    WorkspaceScanError: status.HTTP_500_INTERNAL_SERVER_ERROR,
    IntelligenceNotFoundError: status.HTTP_404_NOT_FOUND,
}


async def ingestion_error_handler(request: Request, exc: IngestionError) -> JSONResponse:
    """Translate an ingestion-domain exception into the standard error envelope.

    Args:
        request: The incoming request.
        exc: The raised ingestion exception.

    Returns:
        A JSON response using the module's status mapping, defaulting to 500
        for any ``IngestionError`` subclass not explicitly mapped.
    """
    status_code = _STATUS_BY_EXCEPTION.get(type(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
    logger.warning("Ingestion error on %s %s: %s", request.method, request.url.path, exc)
    return build_error_response(status_code, str(exc), [{"detail": str(exc)}])


def register_ingestion_exception_handlers(app: FastAPI) -> None:
    """Register the ingestion module's exception handler.

    Args:
        app: The FastAPI application instance.
    """
    app.add_exception_handler(IngestionError, ingestion_error_handler)
