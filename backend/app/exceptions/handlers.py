"""Centralized FastAPI exception handlers.

Every handler returns the standard CodeSage response envelope defined in
CLAUDE.md §10: ``{"success": false, "message": "...", "errors": [...]}``.
No raw stack trace or internal detail is ever returned to the client.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("codesage.exceptions")


def build_error_response(status_code: int, message: str, errors: list[dict[str, Any]]) -> JSONResponse:
    """Build a response following the standard error envelope.

    Args:
        status_code: HTTP status code to return.
        message: Human-readable summary of the failure.
        errors: Structured list of individual error details.

    Returns:
        A ``JSONResponse`` with the standard ``{success, message, errors}`` body.
    """
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "message": message, "errors": errors},
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle request validation failures (422).

    Args:
        request: The incoming request that failed validation.
        exc: The validation error raised by FastAPI/Pydantic.

    Returns:
        A 422 response listing each failed field.
    """
    logger.warning("Validation error on %s %s: %s", request.method, request.url.path, exc.errors())
    errors = [
        {"field": ".".join(str(loc) for loc in err["loc"]), "message": err["msg"], "type": err["type"]}
        for err in exc.errors()
    ]
    return build_error_response(status.HTTP_422_UNPROCESSABLE_ENTITY, "Request validation failed.", errors)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Handle explicit ``HTTPException`` raises.

    Args:
        request: The incoming request.
        exc: The HTTP exception raised by application code.

    Returns:
        A response using the exception's own status code and detail.
    """
    logger.warning("HTTP exception on %s %s: %s", request.method, request.url.path, exc.detail)
    return build_error_response(exc.status_code, str(exc.detail), [{"detail": str(exc.detail)}])


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle any exception not otherwise caught.

    Args:
        request: The incoming request.
        exc: The unexpected exception.

    Returns:
        A generic 500 response; the real exception is logged, never exposed.
    """
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return build_error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "An unexpected error occurred.",
        [{"detail": "Internal server error."}],
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Wire all centralized exception handlers onto the FastAPI app.

    Args:
        app: The FastAPI application instance to register handlers on.
    """
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
