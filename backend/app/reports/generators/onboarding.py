"""Developer Onboarding Guide generator (spec §7) — internal type ``onboarding``."""
from __future__ import annotations

from collections import Counter

from app.reports.evidence import file_evidence, intelligence_evidence
from app.reports.generators import GeneratedReport, RepositoryFacts, evidence_for_verification_from_files
from app.reports.mermaid import module_of
from app.reports.schemas import EvidenceConfidence, ReportSection

_TEST_MARKERS = ("test_", "_test.", "/tests/", "\\tests\\", "/test/", "\\test\\")
_PERSISTENCE_MARKERS = ("model", "schema", "migration", "repository", "db", "database", "orm")


def _is_test_path(path: str) -> bool:
    lowered = path.lower()
    filename = lowered.rsplit("/", 1)[-1]
    if filename in ("tests.py", "test.py", "conftest.py"):
        return True
    return any(marker in lowered for marker in _TEST_MARKERS)


def _looks_like_persistence(path: str) -> bool:
    lowered = path.lower()
    return any(marker in lowered for marker in _PERSISTENCE_MARKERS)


def generate(facts: RepositoryFacts) -> GeneratedReport:
    """Build the deterministic Developer Onboarding Guide.

    Args:
        facts: Already-collected repository data.

    Returns:
        The generator's deterministic output, plus the AI-narrative
        request for the service's single batched synthesis call.
    """
    repository = facts.repository
    intelligence = facts.intelligence
    module_counts = Counter(module_of(path, depth=1) for path in facts.file_paths)

    sections: list[ReportSection] = [
        ReportSection(
            heading="What Is This Repository?",
            content=(
                f"{repository.name} is a {', '.join(intelligence.languages.keys()) if intelligence and intelligence.languages else 'multi-file'} "
                f"repository with {len(facts.files)} files and {len(facts.symbols)} parsed symbols."
            ),
            confidence=EvidenceConfidence.VERIFIED,
            metrics={"total_files": len(facts.files), "total_symbols": len(facts.symbols)},
        )
    ]

    if intelligence is not None and intelligence.entry_points:
        sections.append(
            ReportSection(
                heading="Where Should A Developer Start?",
                content="Start by reading: " + ", ".join(intelligence.entry_points),
                confidence=EvidenceConfidence.VERIFIED,
                evidence=[file_evidence(p, source="repository_intelligence.entry_points") for p in intelligence.entry_points],
                findings=list(intelligence.entry_points),
            )
        )
    else:
        sections.append(
            ReportSection(
                heading="Where Should A Developer Start?",
                content="No conventional entry-point filename was detected — inspect the largest/most-connected modules instead.",
                confidence=EvidenceConfidence.INSUFFICIENT_EVIDENCE,
            )
        )

    sections.append(
        ReportSection(
            heading="Repository Structure",
            content=(
                "Top-level modules: " + ", ".join(f"{name} ({count} files)" for name, count in module_counts.most_common(10))
            ) if module_counts else "No structure could be determined.",
            confidence=EvidenceConfidence.DERIVED,
            metrics={"modules": dict(module_counts.most_common(10))},
        )
    )

    if intelligence is not None and intelligence.largest_modules:
        sections.append(
            ReportSection(
                heading="Important Modules",
                content=(
                    "The most substantial modules (by symbol count): "
                    + ", ".join(f"{m['path']} ({m['symbol_count']} symbols)" for m in intelligence.largest_modules[:5])
                ),
                confidence=EvidenceConfidence.VERIFIED,
                evidence=[file_evidence(m["path"], description=f"{m['symbol_count']} symbols") for m in intelligence.largest_modules[:5]],
                findings=[m["path"] for m in intelligence.largest_modules[:5]],
            )
        )

    if intelligence is not None and intelligence.dependency_hotspots:
        sections.append(
            ReportSection(
                heading="Files Likely To Change For Common Feature Work",
                content=(
                    "Modules with the most dependents (changing these has the widest ripple effect): "
                    + ", ".join(h["module_path"] for h in intelligence.dependency_hotspots[:5])
                ),
                confidence=EvidenceConfidence.DERIVED,
                evidence=[intelligence_evidence("dependency_hotspots", h["module_path"]) for h in intelligence.dependency_hotspots[:5]],
                findings=[h["module_path"] for h in intelligence.dependency_hotspots[:5]],
            )
        )

    persistence_files = [p for p in facts.file_paths if _looks_like_persistence(p)]
    sections.append(
        ReportSection(
            heading="Where Is Persistence/Database Logic Located?",
            content=(
                "Files matching persistence-related naming conventions: " + ", ".join(persistence_files[:10])
            ) if persistence_files else "No files matching common persistence-related naming conventions were found.",
            confidence=EvidenceConfidence.DERIVED,
            evidence=[file_evidence(p) for p in persistence_files[:5]],
            findings=persistence_files[:10],
        )
    )

    test_files = [p for p in facts.file_paths if _is_test_path(p)]
    sections.append(
        ReportSection(
            heading="Where Are The Tests?",
            content=f"{len(test_files)} test-related file(s) found." + (
                " Examples: " + ", ".join(test_files[:5]) if test_files else ""
            ),
            confidence=EvidenceConfidence.DERIVED,
            evidence=[file_evidence(p) for p in test_files[:5]],
            findings=test_files[:10],
        )
    )

    facts_lines = [
        f"repository_name={repository.name}", f"top_level_modules={dict(module_counts.most_common(10))}",
        f"test_file_count={len(test_files)}", f"persistence_file_count={len(persistence_files)}",
    ]
    if intelligence is not None:
        facts_lines += [
            f"entry_points={intelligence.entry_points}", f"largest_modules={intelligence.largest_modules}",
            f"dependency_hotspots={intelligence.dependency_hotspots}",
        ]

    return GeneratedReport(
        title="Developer Onboarding Guide",
        summary=f"A practical starting guide for {repository.name}: {len(facts.files)} files across {len(module_counts)} top-level module(s).",
        sections=sections,
        ai_section_headings=["Getting Started Narrative"],
        ai_facts_context="\n".join(facts_lines),
        ai_evidence_for_verification=evidence_for_verification_from_files(facts.file_paths),
    )
