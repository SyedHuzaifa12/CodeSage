"""Codebase Health Report generator (spec §6) — internal type ``health``.

Deterministic-only, same rationale as ``dependency_risk.py``: every
metric is a direct read or simple aggregation over already-computed
data. Any metric this repository's pipeline doesn't actually produce
(e.g. test coverage percentage, documentation coverage) is explicitly
marked unavailable rather than estimated or invented (spec §6: "do not
invent metrics that are not actually available").
"""
from __future__ import annotations

from app.reports.evidence import file_evidence, intelligence_evidence
from app.reports.generators import GeneratedReport, RepositoryFacts
from app.reports.schemas import EvidenceConfidence, ReportSection

_TEST_MARKERS = ("test_", "_test.", "/tests/", "\\tests\\", "/test/", "\\test\\")
_DOC_NAMES = ("readme.md", "readme.rst", "readme.txt", "contributing.md", "architecture.md")


def _is_test_path(path: str) -> bool:
    lowered = path.lower()
    filename = lowered.rsplit("/", 1)[-1]
    if filename in ("tests.py", "test.py", "conftest.py"):
        return True
    return any(marker in lowered for marker in _TEST_MARKERS)


def _is_doc_path(path: str) -> bool:
    name = path.rsplit("/", 1)[-1].lower()
    return name in _DOC_NAMES or path.lower().startswith("docs/")


def generate(facts: RepositoryFacts) -> GeneratedReport:
    """Build the deterministic Codebase Health Report.

    Args:
        facts: Already-collected repository data.

    Returns:
        The generator's deterministic output (no AI section headings —
        this report type stays fully deterministic).
    """
    repository = facts.repository
    intelligence = facts.intelligence
    file_count = len(facts.files)
    symbol_count = len(facts.symbols)

    sections: list[ReportSection] = [
        ReportSection(
            heading="Repository Size",
            content=f"{file_count} file(s), {symbol_count} symbol(s).",
            confidence=EvidenceConfidence.VERIFIED,
            metrics={"total_files": file_count, "total_symbols": symbol_count},
        )
    ]

    if intelligence is not None:
        sections.append(
            ReportSection(
                heading="Languages",
                content=", ".join(f"{lang} ({count})" for lang, count in (intelligence.languages or {}).items())
                or "Language distribution unavailable.",
                confidence=EvidenceConfidence.VERIFIED,
                metrics={"languages": intelligence.languages},
            )
        )

        largest = intelligence.largest_modules or []
        sections.append(
            ReportSection(
                heading="Largest Modules",
                content=(
                    "Largest modules by symbol count: " + ", ".join(f"{m['path']} ({m['symbol_count']})" for m in largest)
                ) if largest else "No module size data is available.",
                confidence=EvidenceConfidence.VERIFIED,
                evidence=[file_evidence(m["path"], description=f"{m['symbol_count']} symbols") for m in largest[:5]],
                metrics={"largest_modules": largest},
            )
        )

        hotspots = intelligence.dependency_hotspots or []
        sections.append(
            ReportSection(
                heading="Dependency Concentration",
                content=(
                    f"Top dependency hotspot: {hotspots[0]['module_path']} with {hotspots[0]['incoming_dependencies']} incoming dependencies."
                    if hotspots else "No dependency concentration data is available."
                ),
                confidence=EvidenceConfidence.VERIFIED,
                metrics={"dependency_hotspot_count": len(hotspots)},
            )
        )

        sections.append(
            ReportSection(
                heading="Structural Complexity Signals",
                content=(
                    f"{len(intelligence.circular_dependencies)} circular dependency chain(s); "
                    f"{intelligence.inheritance_count} inheritance relationship(s); "
                    f"{intelligence.total_calls} call relationship(s)."
                ),
                confidence=EvidenceConfidence.VERIFIED,
                metrics={
                    "circular_dependency_count": len(intelligence.circular_dependencies),
                    "inheritance_count": intelligence.inheritance_count,
                    "total_calls": intelligence.total_calls,
                },
            )
        )

        orphans = intelligence.orphan_files or []
        sections.append(
            ReportSection(
                heading="Orphan Files",
                content=f"{len(orphans)} orphan file(s) detected." if orphans else "No orphan files detected.",
                confidence=EvidenceConfidence.VERIFIED,
                evidence=[intelligence_evidence("orphan_files", path) for path in orphans[:5]],
                metrics={"orphan_file_count": len(orphans)},
            )
        )
    else:
        sections.append(
            ReportSection(
                heading="Structural Complexity Signals",
                content="Repository intelligence has not been computed yet — this metric is unavailable.",
                confidence=EvidenceConfidence.INSUFFICIENT_EVIDENCE,
            )
        )

    test_files = [f.path for f in facts.files if _is_test_path(f.path)]
    doc_files = [f.path for f in facts.files if _is_doc_path(f.path)]
    sections.append(
        ReportSection(
            heading="Test-Related Structure",
            content=(
                f"{len(test_files)} test-related file(s) found ({len(test_files) / file_count:.0%} of files)."
                if file_count else "No files to assess."
            ),
            confidence=EvidenceConfidence.DERIVED,
            evidence=[file_evidence(p) for p in test_files[:5]],
            metrics={"test_file_count": len(test_files), "test_file_ratio": round(len(test_files) / file_count, 4) if file_count else None},
        )
    )
    sections.append(
        ReportSection(
            heading="Documentation Signals",
            content=(
                f"{len(doc_files)} documentation file(s) found." if doc_files
                else "No conventional documentation files (README, docs/) were found."
            ),
            confidence=EvidenceConfidence.DERIVED,
            evidence=[file_evidence(p) for p in doc_files[:5]],
            metrics={"documentation_file_count": len(doc_files)},
        )
    )

    summary = (
        f"{repository.name}: {file_count} files, {symbol_count} symbols, "
        f"{len(test_files)} test file(s), {len(doc_files)} documentation file(s)"
        f"{', ' + str(len(intelligence.circular_dependencies)) + ' circular dependency chain(s)' if intelligence else ''}."
    )

    return GeneratedReport(title="Codebase Health Report", summary=summary, sections=sections)
