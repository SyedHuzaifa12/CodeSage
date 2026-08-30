"""Reports module request/response DTOs — validation only, no business logic.

``EvidenceConfidence`` (spec §10) is deliberately a NEW, distinct enum
from Sprint 5's ``app.ai.schemas.verification.VerificationStatus`` —
see ADR-022. ``VerificationStatus`` describes how well one LLM answer's
citations verify against evidence *for that answer*; ``EvidenceConfidence``
describes the provenance of one *report section/statement*: was it read
straight from the database (``VERIFIED``), computed by combining
deterministic facts (``DERIVED``), AI-synthesized prose that verified
fully (also ``DERIVED``, since the underlying facts were confirmed), AI
prose with some unverified citations (``PARTIAL``), or AI prose that
could not be grounded at all (``INSUFFICIENT_EVIDENCE`` — never
presented as fact).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

REPORT_TYPE_TITLES: dict[str, str] = {
    "summary": "Repository Overview",
    "architecture": "Architecture Report",
    "dependency_risk": "Dependency & Risk Report",
    "health": "Codebase Health Report",
    "onboarding": "Developer Onboarding Guide",
}

# The five report types Sprint 6 actually implements. ``impact`` remains
# a reserved, unused value in ``models.report.VALID_REPORT_TYPES``
# (ADR-016/§11) — never exposed through this module's API.
VALID_SPRINT6_REPORT_TYPES: tuple[str, ...] = (
    "summary", "architecture", "dependency_risk", "health", "onboarding",
)


class EvidenceConfidence(str, Enum):
    """How a report statement's provenance was established — see module docstring."""

    VERIFIED = "verified"
    DERIVED = "derived"
    PARTIAL = "partial"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class EvidenceReference(BaseModel):
    """One piece of repository evidence a report statement is grounded in (spec §10)."""

    model_config = ConfigDict(from_attributes=True)

    source: str = Field(..., description="Where this fact came from, e.g. 'repository_intelligence', 'relationships', 'files', 'ai_synthesis'.")
    file_path: Optional[str] = None
    symbol_name: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    relationship_type: Optional[str] = None
    description: Optional[str] = None


class ReportSection(BaseModel):
    """One structured section of a report (spec §17) — never a single giant text blob."""

    model_config = ConfigDict(from_attributes=True)

    heading: str
    content: str
    confidence: EvidenceConfidence
    evidence: list[EvidenceReference] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)
    findings: list[str] = Field(default_factory=list)


class ReportDiagram(BaseModel):
    """One Mermaid diagram attached to a report."""

    model_config = ConfigDict(from_attributes=True)

    title: str
    diagram_type: str
    mermaid_code: str


class GenerateReportRequest(BaseModel):
    """Request body for ``POST /repositories/{id}/reports/{report_type}``."""

    force_regenerate: bool = False


class ReportResponse(BaseModel):
    """Payload shape for a single structured report (spec §17)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    repository_id: uuid.UUID
    report_type: str
    status: str
    title: Optional[str] = None
    summary: Optional[str] = None
    sections: list[ReportSection] = Field(default_factory=list)
    diagrams: list[ReportDiagram] = Field(default_factory=list)
    generation_metadata: dict = Field(default_factory=dict)
    repository_version: Optional[str] = None
    generated_at: Optional[datetime] = None
    created_at: datetime
    error_message: Optional[str] = None
    stale: bool = False


class ReportListData(BaseModel):
    """Payload shape for ``GET /repositories/{id}/reports``."""

    repository_id: uuid.UUID
    latest_only: bool
    reports: list[ReportResponse]
