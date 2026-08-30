"""Repository Overview Report generator (spec §3) — internal type ``summary``."""
from __future__ import annotations

from collections import Counter

from app.reports.evidence import file_evidence, intelligence_evidence
from app.reports.generators import GeneratedReport, RepositoryFacts, evidence_for_verification_from_files
from app.reports.mermaid import module_of
from app.reports.schemas import EvidenceConfidence, ReportSection

_TEST_MARKERS = ("test_", "_test.", "/tests/", "\\tests\\", "/test/", "\\test\\")
_CONFIG_NAMES = (
    "dockerfile", "docker-compose.yml", "docker-compose.yaml", ".env.example", "pyproject.toml", "requirements.txt",
    "package.json", "setup.py", "setup.cfg", "alembic.ini", "pytest.ini",
)


def _is_test_path(path: str) -> bool:
    lowered = path.lower()
    filename = lowered.rsplit("/", 1)[-1]
    if filename in ("tests.py", "test.py", "conftest.py"):
        return True
    return any(marker in lowered for marker in _TEST_MARKERS)


def _is_config_path(path: str) -> bool:
    name = path.rsplit("/", 1)[-1].lower()
    return name in _CONFIG_NAMES or name.endswith((".ini", ".cfg", ".toml", ".yaml", ".yml"))


def generate(facts: RepositoryFacts) -> GeneratedReport:
    """Build the deterministic Repository Overview Report.

    Args:
        facts: Already-collected repository data.

    Returns:
        The generator's deterministic output, plus the AI-narrative
        request for the service's single batched synthesis call.
    """
    repository = facts.repository
    intelligence = facts.intelligence
    file_count = len(facts.files)
    symbol_count = len(facts.symbols)

    sections: list[ReportSection] = [
        ReportSection(
            heading="Repository Statistics",
            content=f"{repository.name} contains {file_count} indexed files and {symbol_count} parsed symbols.",
            confidence=EvidenceConfidence.VERIFIED,
            evidence=[file_evidence(f.path) for f in facts.files[:5]],
            metrics={"total_files": file_count, "total_symbols": symbol_count},
        )
    ]

    if intelligence is not None:
        languages = intelligence.languages or {}
        sections.append(
            ReportSection(
                heading="Languages & Technologies",
                content=(
                    "Detected languages by file share: " + ", ".join(f"{lang} ({count})" for lang, count in languages.items())
                    if languages else "No language distribution is available for this repository."
                ),
                confidence=EvidenceConfidence.VERIFIED,
                evidence=[intelligence_evidence("languages", "Language distribution computed during ingestion.")],
                metrics={"languages": languages},
            )
        )

        directory_counts = Counter(module_of(f.path, depth=1) for f in facts.files)
        sections.append(
            ReportSection(
                heading="Repository Structure",
                content=(
                    "Major top-level directories: "
                    + ", ".join(f"{name} ({count} files)" for name, count in directory_counts.most_common(10))
                ) if directory_counts else "No directory structure could be determined.",
                confidence=EvidenceConfidence.DERIVED,
                evidence=[file_evidence(f.path) for f in facts.files[:5]],
                metrics={"top_level_directories": dict(directory_counts.most_common(10))},
            )
        )

        sections.append(
            ReportSection(
                heading="Entry Points",
                content=(
                    "Identified application entry points: " + ", ".join(intelligence.entry_points)
                    if intelligence.entry_points else "No conventional entry-point filenames were found."
                ),
                confidence=EvidenceConfidence.VERIFIED,
                evidence=[file_evidence(path, source="repository_intelligence.entry_points") for path in intelligence.entry_points],
                findings=list(intelligence.entry_points),
            )
        )

        hotspots = intelligence.dependency_hotspots or []
        sections.append(
            ReportSection(
                heading="Dependency Hotspots",
                content=(
                    "Modules with the most incoming dependencies: "
                    + ", ".join(f"{h['module_path']} ({h['incoming_dependencies']} dependents)" for h in hotspots)
                ) if hotspots else "No dependency hotspots were detected.",
                confidence=EvidenceConfidence.VERIFIED,
                evidence=[intelligence_evidence("dependency_hotspots", f"{h['module_path']}: {h['incoming_dependencies']} incoming dependencies") for h in hotspots],
                metrics={"hotspots": hotspots},
            )
        )

        sections.append(
            ReportSection(
                heading="Architectural Observations",
                content=(
                    " ".join(intelligence.architecture_hints) if intelligence.architecture_hints
                    else "No notable architectural signals were detected."
                ),
                confidence=EvidenceConfidence.DERIVED,
                evidence=[intelligence_evidence("architecture_hints", hint) for hint in intelligence.architecture_hints],
                findings=list(intelligence.architecture_hints),
            )
        )

    test_files = [f.path for f in facts.files if _is_test_path(f.path)]
    config_files = [f.path for f in facts.files if _is_config_path(f.path)]
    sections.append(
        ReportSection(
            heading="Testing & Configuration",
            content=(
                f"{len(test_files)} test-related file(s) and {len(config_files)} configuration file(s) were detected."
            ),
            confidence=EvidenceConfidence.DERIVED,
            evidence=[file_evidence(p, source="files") for p in (test_files[:3] + config_files[:3])],
            metrics={"test_file_count": len(test_files), "config_file_count": len(config_files)},
        )
    )

    facts_lines = [
        f"repository_name={repository.name}", f"total_files={file_count}", f"total_symbols={symbol_count}",
    ]
    if intelligence is not None:
        facts_lines += [
            f"languages={intelligence.languages}", f"entry_points={intelligence.entry_points}",
            f"architecture_hints={intelligence.architecture_hints}",
            f"dependency_hotspots={intelligence.dependency_hotspots}",
        ]

    return GeneratedReport(
        title="Repository Overview",
        summary=f"{repository.name} — {file_count} files, {symbol_count} symbols across {len(intelligence.languages) if intelligence else 0} language(s).",
        sections=sections,
        ai_section_headings=["Narrative Overview"],
        ai_facts_context="\n".join(facts_lines),
        ai_evidence_for_verification=evidence_for_verification_from_files(facts.file_paths),
    )
