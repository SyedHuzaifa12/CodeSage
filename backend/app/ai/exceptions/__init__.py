"""AI Engine exceptions and their HTTP mapping.

Domain exceptions are raised by ``services/ai_service.py`` and
translated here into the standard error envelope (CLAUDE.md §14) —
mirrors ``app.retrieval.exceptions`` exactly.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.exceptions.handlers import build_error_response

logger = logging.getLogger("codesage.ai.exceptions")


class AIError(Exception):
    """Base class for all AI-module errors."""


class RepositoryNotReadyForAIError(AIError):
    """Raised when a repository has not finished knowledge-indexing yet."""


class InvalidAskRequestError(AIError):
    """Raised when an ``/ask`` request is structurally invalid (e.g. an unknown source name)."""


class LLMProviderError(AIError):
    """Raised when the configured LLM provider call fails (after retries)."""


class LLMTimeoutError(AIError):
    """Raised when the whole AI pipeline exceeds its total timeout budget."""


_STATUS_BY_EXCEPTION: dict[type[AIError], int] = {
    RepositoryNotReadyForAIError: status.HTTP_409_CONFLICT,
    InvalidAskRequestError: status.HTTP_400_BAD_REQUEST,
    LLMProviderError: status.HTTP_503_SERVICE_UNAVAILABLE,
    LLMTimeoutError: status.HTTP_504_GATEWAY_TIMEOUT,
}


async def ai_error_handler(request: Request, exc: AIError) -> JSONResponse:
    """Translate an AI-domain exception into the standard error envelope.

    Args:
        request: The incoming request.
        exc: The raised AI exception.

    Returns:
        A JSON response using the module's status mapping, defaulting
        to 500 for any ``AIError`` subclass not explicitly mapped.
    """
    status_code = _STATUS_BY_EXCEPTION.get(type(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
    logger.warning("AI error on %s %s: %s", request.method, request.url.path, exc)
    return build_error_response(status_code, str(exc), [{"detail": str(exc)}])


def register_ai_exception_handlers(app: FastAPI) -> None:
    """Register the AI module's exception handler.

    Args:
        app: The FastAPI application instance.
    """
    app.add_exception_handler(AIError, ai_error_handler)
