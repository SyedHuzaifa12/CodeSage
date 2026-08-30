"""Small, pure, generic helpers shared across the reports module (CLAUDE.md §11).

No business logic lives here beyond formatting/validation utilities
that don't belong to any single generator or to the service's
orchestration flow.
"""
from __future__ import annotations

from app.models.report import Report
from app.reports.exceptions import InvalidReportTypeError
from app.reports.schemas import REPORT_TYPE_TITLES, VALID_SPRINT6_REPORT_TYPES, ReportSection


def validate_report_type(report_type: str) -> str:
    """Validate a ``report_type`` path parameter against Sprint 6's supported values.

    Args:
        report_type: The raw path parameter.

    Returns:
        The same value, unchanged, if valid.

    Raises:
        InvalidReportTypeError: If ``report_type`` is not one of the
            five Sprint-6-relevant values (``impact`` is a reserved,
            distinct future feature — never accepted here even though
            it's a valid ``models.report.VALID_REPORT_TYPES`` value).
    """
    if report_type not in VALID_SPRINT6_REPORT_TYPES:
        raise InvalidReportTypeError(
            f"'{report_type}' is not a supported report type. Valid values: {', '.join(VALID_SPRINT6_REPORT_TYPES)}."
        )
    return report_type


def default_title(report_type: str) -> str:
    """Return the human-readable title for a report type.

    Args:
        report_type: A validated Sprint 6 report type.

    Returns:
        The display title (e.g. ``"summary"`` -> ``"Repository Overview"``).
    """
    return REPORT_TYPE_TITLES.get(report_type, report_type.replace("_", " ").title())


def render_content_text(title: str, summary: str | None, sections: list[ReportSection]) -> str:
    """Render a structured report as a single deterministic Markdown-ish text blob.

    Populates ``Report.content`` (kept ``NOT NULL`` for backward
    compatibility with the pre-Sprint-6 contract — see
    ``models/report.py``'s docstring) from the same structured data the
    API returns, so the two representations can never drift out of sync.

    Args:
        title: The report's title.
        summary: The report's top-level summary, if any.
        sections: The report's structured sections.

    Returns:
        A plain-text rendering suitable for the legacy ``content`` column.
    """
    parts = [f"# {title}"]
    if summary:
        parts.append(summary)
    for section in sections:
        parts.append(f"## {section.heading}\n\n{section.content}")
        if section.findings:
            parts.append("\n".join(f"- {finding}" for finding in section.findings))
    return "\n\n".join(parts)


def dedupe_latest_per_type(reports: list[Report]) -> list[Report]:
    """Keep only the newest row per ``report_type`` from an already-newest-first list.

    Args:
        reports: Report rows for one repository, ordered newest first
            (see ``repository.py::list_for_repository``).

    Returns:
        One row per distinct ``report_type`` — the first (newest)
        occurrence encountered, in the same relative order.
    """
    seen: set[str] = set()
    latest: list[Report] = []
    for report in reports:
        if report.report_type in seen:
            continue
        seen.add(report.report_type)
        latest.append(report)
    return latest


def is_stale(report_repository_version: str | None, current_repository_version: str) -> bool:
    """Determine whether a persisted report is stale relative to the repository's current state.

    Args:
        report_repository_version: The version string recorded on the report row.
        current_repository_version: The repository's current version
            (see ``app.retrieval.cache.get_corpus_version``).

    Returns:
        ``True`` if the repository has been re-indexed since this
        report was generated (or the report predates version tracking).
    """
    return report_repository_version != current_repository_version
