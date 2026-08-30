"""Reports module exceptions and their HTTP mapping.

Domain exceptions are raised by ``service.py`` and translated here into
the standard error envelope (CLAUDE.md §14) — mirrors
``app.ai.exceptions``/``app.knowledge.exceptions`` exactly.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.exceptions.handlers import build_error_response

logger = logging.getLogger("codesage.reports.exceptions")


class ReportError(Exception):
    """Base class for all reports-module errors."""


class ReportRepositoryNotIndexedError(ReportError):
    """Raised when a report is requested/generated before knowledge-indexing has finished."""


class InvalidReportTypeError(ReportError):
    """Raised when a ``report_type`` path parameter is not one of Sprint 6's supported values."""


class ReportGenerationError(ReportError):
    """Raised when report generation fails unexpectedly (deterministic collection, not AI synthesis)."""


class ReportNotFoundError(ReportError):
    """Raised when no report (of the requested status) exists yet for a repository/type."""


_STATUS_BY_EXCEPTION: dict[type[ReportError], int] = {
    ReportRepositoryNotIndexedError: status.HTTP_409_CONFLICT,
    InvalidReportTypeError: status.HTTP_400_BAD_REQUEST,
    ReportGenerationError: status.HTTP_502_BAD_GATEWAY,
    ReportNotFoundError: status.HTTP_404_NOT_FOUND,
}


async def report_error_handler(request: Request, exc: ReportError) -> JSONResponse:
    """Translate a reports-domain exception into the standard error envelope.

    Args:
        request: The incoming request.
        exc: The raised reports exception.

    Returns:
        A JSON response using the module's status mapping, defaulting
        to 500 for any ``ReportError`` subclass not explicitly mapped.
    """
    status_code = _STATUS_BY_EXCEPTION.get(type(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
    logger.warning("Report error on %s %s: %s", request.method, request.url.path, exc)
    return build_error_response(status_code, str(exc), [{"detail": str(exc)}])


def register_reports_exception_handlers(app: FastAPI) -> None:
    """Register the reports module's exception handler.

    Args:
        app: The FastAPI application instance.
    """
    app.add_exception_handler(ReportError, report_error_handler)
