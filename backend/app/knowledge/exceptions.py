"""Knowledge module exceptions and their HTTP mapping.

Domain exceptions are raised by ``service.py`` and translated here into
the standard error envelope (CLAUDE.md §14).
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.exceptions.handlers import build_error_response

logger = logging.getLogger("codesage.knowledge.exceptions")


class KnowledgeError(Exception):
    """Base class for all knowledge-module errors."""


class RepositoryNotIndexedError(KnowledgeError):
    """Raised when knowledge state is requested before any indexing has run."""


class KnowledgeIndexingError(KnowledgeError):
    """Raised when the knowledge-indexing pipeline fails at the repository level."""


_STATUS_BY_EXCEPTION: dict[type[KnowledgeError], int] = {
    RepositoryNotIndexedError: status.HTTP_404_NOT_FOUND,
    KnowledgeIndexingError: status.HTTP_500_INTERNAL_SERVER_ERROR,
}


async def knowledge_error_handler(request: Request, exc: KnowledgeError) -> JSONResponse:
    """Translate a knowledge-domain exception into the standard error envelope.

    Args:
        request: The incoming request.
        exc: The raised knowledge exception.

    Returns:
        A JSON response using the module's status mapping, defaulting to
        500 for any ``KnowledgeError`` subclass not explicitly mapped.
    """
    status_code = _STATUS_BY_EXCEPTION.get(type(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
    logger.warning("Knowledge error on %s %s: %s", request.method, request.url.path, exc)
    return build_error_response(status_code, str(exc), [{"detail": str(exc)}])


def register_knowledge_exception_handlers(app: FastAPI) -> None:
    """Register the knowledge module's exception handler.

    Args:
        app: The FastAPI application instance.
    """
    app.add_exception_handler(KnowledgeError, knowledge_error_handler)
