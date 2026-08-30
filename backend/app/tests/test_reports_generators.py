"""Unit tests for deterministic report generators — fixture data only, no live DB (spec §20)."""
from __future__ import annotations

import uuid

from app.models.file import File
from app.models.relationship import Relationship
from app.models.repository import Repository
from app.models.repository_intelligence import RepositoryIntelligence
from app.models.symbol import Symbol
from app.reports.generators import RepositoryFacts
from app.reports.generators import architecture, dependency_risk, health, onboarding, overview
from app.reports.schemas import EvidenceConfidence


def _make_facts(*, with_intelligence: bool = True) -> RepositoryFacts:
    repository_id = uuid.uuid4()
    repository = Repository(id=repository_id, name="demo-repo", local_path="/tmp/demo")

    files = [
        File(id=uuid.uuid4(), repository_id=repository_id, path="app/main.py", language="Python"),
        File(id=uuid.uuid4(), repository_id=repository_id, path="app/models/user.py", language="Python"),
        File(id=uuid.uuid4(), repository_id=repository_id, path="tests/test_user.py", language="Python"),
        File(id=uuid.uuid4(), repository_id=repository_id, path="README.md", language=None),
    ]
    symbols = [
        Symbol(
            id=uuid.uuid4(), file_id=files[1].id, name="User", qualified_name="app.models.user.User",
            symbol_type="class", visibility="public", start_line=1, end_line=20,
        )
    ]
    relationships = [
        Relationship(
            id=uuid.uuid4(), repository_id=repository_id, source_symbol="app.main",
            target_symbol="app.models.user", relationship_type="depends_on",
        ),
        Relationship(
            id=uuid.uuid4(), repository_id=repository_id, source_symbol="app.main.run",
            target_symbol="app.models.user.User", relationship_type="calls",
        ),
    ]

    intelligence = None
    if with_intelligence:
        intelligence = RepositoryIntelligence(
            id=uuid.uuid4(), repository_id=repository_id, status="ready",
            languages={"Python": 3, "Markdown": 1}, entry_points=["app/main.py"],
            largest_modules=[{"path": "app/models/user.py", "symbol_count": 1}],
            dependency_hotspots=[{"module_path": "app.models.user", "incoming_dependencies": 1}],
            architecture_hints=["Contains a test suite"], circular_dependencies=[], orphan_files=["README.md"],
            inheritance_count=0, total_calls=1,
        )

    return RepositoryFacts(
        repository=repository, intelligence=intelligence, files=files, symbols=symbols, relationships=relationships,
    )


class TestOverviewGenerator:
    def test_produces_sections_and_ai_request(self) -> None:
        report = overview.generate(_make_facts())
        assert report.title == "Repository Overview"
        headings = {section.heading for section in report.sections}
        assert "Repository Statistics" in headings
        assert "Entry Points" in headings
        assert report.ai_section_headings == ["Narrative Overview"]
        assert "demo-repo" in report.ai_facts_context

    def test_verified_confidence_for_direct_counts(self) -> None:
        report = overview.generate(_make_facts())
        stats_section = next(s for s in report.sections if s.heading == "Repository Statistics")
        assert stats_section.confidence == EvidenceConfidence.VERIFIED
        assert stats_section.metrics["total_files"] == 4

    def test_missing_intelligence_still_produces_a_report(self) -> None:
        report = overview.generate(_make_facts(with_intelligence=False))
        assert any(s.heading == "Repository Statistics" for s in report.sections)


class TestArchitectureGenerator:
    def test_produces_diagrams(self) -> None:
        report = architecture.generate(_make_facts())
        assert report.diagrams
        assert report.diagrams[0].mermaid_code.startswith("flowchart TD")

    def test_no_dependency_edges_is_flagged_insufficient(self) -> None:
        facts = _make_facts()
        facts.relationships = [r for r in facts.relationships if r.relationship_type != "depends_on"]
        report = architecture.generate(facts)
        dependency_section = next(s for s in report.sections if s.heading == "Dependency Direction")
        assert dependency_section.confidence == EvidenceConfidence.INSUFFICIENT_EVIDENCE

    def test_circular_dependencies_are_verified_and_flagged(self) -> None:
        facts = _make_facts()
        facts.intelligence.circular_dependencies = [["app.a", "app.b", "app.a"]]
        report = architecture.generate(facts)
        risk_section = next(s for s in report.sections if s.heading == "Tightly Coupled Areas & Architectural Risks")
        assert risk_section.confidence == EvidenceConfidence.VERIFIED
        assert risk_section.findings


class TestDependencyRiskGenerator:
    def test_is_deterministic_only(self) -> None:
        report = dependency_risk.generate(_make_facts())
        assert report.ai_section_headings == []
        assert report.ai_facts_context == ""

    def test_high_risk_module_flagged_when_cyclic_and_hot(self) -> None:
        facts = _make_facts()
        facts.intelligence.dependency_hotspots = [{"module_path": "app.core", "incoming_dependencies": 10}]
        facts.intelligence.circular_dependencies = [["app.core", "app.other", "app.core"]]
        report = dependency_risk.generate(facts)
        hotspot_section = next(s for s in report.sections if s.heading == "Dependency Hotspots")
        assert any("high-risk" in finding for finding in hotspot_section.findings)

    def test_orphan_files_reported(self) -> None:
        report = dependency_risk.generate(_make_facts())
        orphan_section = next(s for s in report.sections if s.heading == "Orphan Files")
        assert "README.md" in orphan_section.findings


class TestHealthGenerator:
    def test_is_deterministic_only(self) -> None:
        report = health.generate(_make_facts())
        assert report.ai_section_headings == []

    def test_reports_unavailable_metric_when_no_intelligence(self) -> None:
        report = health.generate(_make_facts(with_intelligence=False))
        complexity_section = next(s for s in report.sections if s.heading == "Structural Complexity Signals")
        assert complexity_section.confidence == EvidenceConfidence.INSUFFICIENT_EVIDENCE

    def test_test_file_ratio_computed(self) -> None:
        report = health.generate(_make_facts())
        test_section = next(s for s in report.sections if s.heading == "Test-Related Structure")
        assert test_section.metrics["test_file_count"] == 1


class TestOnboardingGenerator:
    def test_identifies_entry_points_and_tests(self) -> None:
        report = onboarding.generate(_make_facts())
        start_section = next(s for s in report.sections if s.heading == "Where Should A Developer Start?")
        assert "app/main.py" in start_section.content
        test_section = next(s for s in report.sections if s.heading == "Where Are The Tests?")
        assert "tests/test_user.py" in test_section.findings

    def test_no_entry_points_marks_insufficient(self) -> None:
        facts = _make_facts()
        facts.intelligence.entry_points = []
        report = onboarding.generate(facts)
        start_section = next(s for s in report.sections if s.heading == "Where Should A Developer Start?")
        assert start_section.confidence == EvidenceConfidence.INSUFFICIENT_EVIDENCE
