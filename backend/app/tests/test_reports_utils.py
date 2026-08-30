"""Unit tests for report-type validation, staleness detection, and dedup helpers."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.models.report import Report
from app.reports.exceptions import InvalidReportTypeError
from app.reports.utils import dedupe_latest_per_type, default_title, is_stale, render_content_text, validate_report_type
from app.reports.schemas import EvidenceConfidence, ReportSection


class TestValidateReportType:
    @pytest.mark.parametrize("report_type", ["summary", "architecture", "dependency_risk", "health", "onboarding"])
    def test_valid_types_pass_through(self, report_type: str) -> None:
        assert validate_report_type(report_type) == report_type

    def test_impact_is_rejected(self) -> None:
        """``impact`` is a valid ORM-level type (ADR-016) but not exposed via Sprint 6's API."""
        with pytest.raises(InvalidReportTypeError):
            validate_report_type("impact")

    def test_unknown_type_is_rejected(self) -> None:
        with pytest.raises(InvalidReportTypeError):
            validate_report_type("not_a_real_type")


class TestDefaultTitle:
    def test_known_type(self) -> None:
        assert default_title("summary") == "Repository Overview"

    def test_unknown_type_falls_back_to_title_case(self) -> None:
        assert default_title("some_new_type") == "Some New Type"


class TestIsStale:
    def test_matching_versions_not_stale(self) -> None:
        assert is_stale("v1", "v1") is False

    def test_differing_versions_are_stale(self) -> None:
        assert is_stale("v1", "v2") is True

    def test_none_version_is_stale(self) -> None:
        assert is_stale(None, "v1") is True


class TestDedupeLatestPerType:
    def _make_report(self, report_type: str, created_at) -> Report:
        return Report(id=uuid.uuid4(), repository_id=uuid.uuid4(), report_type=report_type, content="x", created_at=created_at)

    def test_keeps_first_occurrence_per_type(self) -> None:
        now = datetime.now(timezone.utc)
        newest_summary = self._make_report("summary", now)
        older_summary = self._make_report("summary", now)
        architecture = self._make_report("architecture", now)
        deduped = dedupe_latest_per_type([newest_summary, older_summary, architecture])
        assert deduped == [newest_summary, architecture]


class TestRenderContentText:
    def test_includes_title_summary_and_sections(self) -> None:
        sections = [
            ReportSection(heading="Stats", content="10 files", confidence=EvidenceConfidence.VERIFIED, findings=["a finding"]),
        ]
        text = render_content_text("My Report", "A summary.", sections)
        assert "My Report" in text
        assert "A summary." in text
        assert "Stats" in text
        assert "10 files" in text
        assert "a finding" in text
