"""Reports REST API — routes only, no business logic (CLAUDE.md §10).

Nested under ``/repositories/{repository_id}/reports``, matching every
other module's resource-scoped routing convention.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.postgres import get_db
from app.reports.exceptions import ReportNotFoundError
from app.reports.schemas import GenerateReportRequest, ReportListData, ReportResponse
from app.reports.service import ReportService
from app.schemas.envelope import SuccessResponse

router = APIRouter(prefix="/repositories/{repository_id}/reports", tags=["reports"])


def get_report_service(
    session: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> ReportService:
    """Build a request-scoped :class:`ReportService`.

    Args:
        session: Injected database session.
        settings: Injected application settings.

    Returns:
        A service instance bound to this request's session.
    """
    return ReportService(session=session, settings=settings)


@router.post("/{report_type}", response_model=SuccessResponse[ReportResponse])
async def generate_report(
    repository_id: uuid.UUID, report_type: str, payload: GenerateReportRequest = GenerateReportRequest(),
    service: ReportService = Depends(get_report_service),
) -> SuccessResponse[ReportResponse]:
    """Generate or return a valid cached/existing report for one repository.

    Cache-first and idempotent (spec §8/§12): a valid cached or
    still-current persisted report is returned immediately; the full
    deterministic-collection -> evidence-assembly -> optional single
    AI-synthesis-call -> verification -> persistence pipeline only runs
    when no valid report exists yet, the repository has been
    re-indexed since the last one, or ``force_regenerate`` is set.

    Args:
        repository_id: The repository to report on.
        report_type: One of ``summary``, ``architecture``,
            ``dependency_risk``, ``health``, ``onboarding``.
        payload: Optional generation overrides.
        service: Injected report service.

    Returns:
        The structured report. A generation failure is reported as
        ``status="failed"`` with ``error_message`` set, not a 500.
    """
    data = await service.generate_or_get(repository_id, report_type, force_regenerate=payload.force_regenerate)
    message = "Report generated." if data.status == "ready" else "Report generation failed."
    return SuccessResponse(message=message, data=data)


@router.get("/{report_type}", response_model=SuccessResponse[ReportResponse])
async def get_report(
    repository_id: uuid.UUID, report_type: str, service: ReportService = Depends(get_report_service),
) -> SuccessResponse[ReportResponse]:
    """Fetch the latest ``ready`` report for one repository/type, without generating one.

    Args:
        repository_id: The repository to look up.
        report_type: One of ``summary``, ``architecture``,
            ``dependency_risk``, ``health``, ``onboarding``.
        service: Injected report service.

    Returns:
        The latest ready report, with ``stale`` set if the repository
        has since been re-indexed.

    Raises:
        ReportNotFoundError: If no report of this type has ever been generated.
    """
    data = await service.get_latest(repository_id, report_type)
    if data is None:
        raise ReportNotFoundError(f"No '{report_type}' report has been generated yet for repository '{repository_id}'.")
    return SuccessResponse(message="Report retrieved.", data=data)


@router.get("", response_model=SuccessResponse[ReportListData])
async def list_reports(
    repository_id: uuid.UUID,
    latest_only: bool = Query(default=True, description="One row per report type (default) vs. full history."),
    service: ReportService = Depends(get_report_service),
) -> SuccessResponse[ReportListData]:
    """List a repository's reports.

    Args:
        repository_id: The repository to list reports for.
        latest_only: If ``True`` (default), one row per report type; if
            ``False``, every generation attempt (full history).
        service: Injected report service.

    Returns:
        The matching reports, newest first.
    """
    reports = await service.list_reports(repository_id, latest_only=latest_only)
    data = ReportListData(repository_id=repository_id, latest_only=latest_only, reports=reports)
    return SuccessResponse(message="Reports retrieved.", data=data)
