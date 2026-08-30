"""Retrieval module exceptions and their HTTP mapping.

Domain exceptions are raised by ``service.py`` and translated here into
the standard error envelope (CLAUDE.md §14). A repository with no
indexed knowledge yet is deliberately *not* an exception here — it's a
valid, empty result set (see ``service.py``'s handling), matching this
sprint's "handle empty/no-result cases cleanly" requirement.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.exceptions.handlers import build_error_response

logger = logging.getLogger("codesage.retrieval.exceptions")


class RetrievalError(Exception):
    """Base class for all retrieval-module errors."""


class InvalidQueryError(RetrievalError):
    """Raised when a query request is structurally invalid (e.g. an unknown source name)."""


_STATUS_BY_EXCEPTION: dict[type[RetrievalError], int] = {
    InvalidQueryError: status.HTTP_400_BAD_REQUEST,
}


async def retrieval_error_handler(request: Request, exc: RetrievalError) -> JSONResponse:
    """Translate a retrieval-domain exception into the standard error envelope.

    Args:
        request: The incoming request.
        exc: The raised retrieval exception.

    Returns:
        A JSON response using the module's status mapping, defaulting
        to 500 for any ``RetrievalError`` subclass not explicitly mapped.
    """
    status_code = _STATUS_BY_EXCEPTION.get(type(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
    logger.warning("Retrieval error on %s %s: %s", request.method, request.url.path, exc)
    return build_error_response(status_code, str(exc), [{"detail": str(exc)}])


def register_retrieval_exception_handlers(app: FastAPI) -> None:
    """Register the retrieval module's exception handler.

    Args:
        app: The FastAPI application instance.
    """
    app.add_exception_handler(RetrievalError, retrieval_error_handler)
