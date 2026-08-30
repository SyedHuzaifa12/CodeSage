"""Architecture Report generator (spec §4) — internal type ``architecture``."""
from __future__ import annotations

from collections import Counter

from app.reports.evidence import file_evidence, intelligence_evidence, relationship_evidence
from app.reports.generators import GeneratedReport, RepositoryFacts, evidence_for_verification_from_files
from app.reports.mermaid import build_dependency_flow_diagram, build_module_diagram, module_of
from app.reports.schemas import EvidenceConfidence, ReportDiagram, ReportSection

_MAX_COUPLED_PAIRS = 5


def generate(facts: RepositoryFacts) -> GeneratedReport:
    """Build the deterministic Architecture Report, including real-data Mermaid diagrams.

    Args:
        facts: Already-collected repository data.

    Returns:
        The generator's deterministic output. Diagrams are built here
        (not by the AI synthesis step) — the graph data is the sole
        source of truth for edges/nodes (ADR-024).
    """
    repository = facts.repository
    intelligence = facts.intelligence
    depends_on_edges = facts.depends_on_edges
    module_counts = Counter(module_of(path, depth=1) for path in facts.file_paths)

    sections: list[ReportSection] = [
        ReportSection(
            heading="Major Modules",
            content=(
                "Top-level modules by file count: "
                + ", ".join(f"{name} ({count} files)" for name, count in module_counts.most_common(10))
            ) if module_counts else "No modules could be identified from repository structure.",
            confidence=EvidenceConfidence.DERIVED,
            evidence=[file_evidence(p) for p in facts.file_paths[:5]],
            metrics={"modules": dict(module_counts.most_common(10))},
        )
    ]

    if intelligence is not None and intelligence.entry_points:
        sections.append(
            ReportSection(
                heading="Entry Points",
                content="Execution begins at: " + ", ".join(intelligence.entry_points),
                confidence=EvidenceConfidence.VERIFIED,
                evidence=[file_evidence(p, source="repository_intelligence.entry_points") for p in intelligence.entry_points],
                findings=list(intelligence.entry_points),
            )
        )

    if depends_on_edges:
        edge_desc = [
            relationship_evidence(source, target, "depends_on") for source, target in depends_on_edges[:10]
        ]
        sections.append(
            ReportSection(
                heading="Dependency Direction",
                content=(
                    f"{len(depends_on_edges)} resolved module-level dependency edge(s) were found — "
                    "see the dependency-flow diagram for the most connected modules."
                ),
                confidence=EvidenceConfidence.DERIVED,
                evidence=edge_desc,
                metrics={"total_dependency_edges": len(depends_on_edges)},
            )
        )
    else:
        sections.append(
            ReportSection(
                heading="Dependency Direction",
                content="No resolved module-level dependency edges are available — this section is partial.",
                confidence=EvidenceConfidence.INSUFFICIENT_EVIDENCE,
            )
        )

    if intelligence is not None and intelligence.circular_dependencies:
        cycle_descriptions = [" -> ".join(cycle) for cycle in intelligence.circular_dependencies[:_MAX_COUPLED_PAIRS]]
        sections.append(
            ReportSection(
                heading="Tightly Coupled Areas & Architectural Risks",
                content=(
                    f"{len(intelligence.circular_dependencies)} circular dependency chain(s) were detected, "
                    "indicating tightly coupled modules: " + "; ".join(cycle_descriptions)
                ),
                confidence=EvidenceConfidence.VERIFIED,
                evidence=[intelligence_evidence("circular_dependencies", desc) for desc in cycle_descriptions],
                findings=cycle_descriptions,
            )
        )
    else:
        sections.append(
            ReportSection(
                heading="Tightly Coupled Areas & Architectural Risks",
                content="No circular dependencies were detected in the resolved dependency graph.",
                confidence=EvidenceConfidence.VERIFIED,
            )
        )

    diagrams = [
        ReportDiagram(
            title="Module Overview", diagram_type="module",
            mermaid_code=build_module_diagram(facts.file_paths, depends_on_edges),
        ),
    ]
    if intelligence is not None and intelligence.dependency_hotspots:
        diagrams.append(
            ReportDiagram(
                title="Dependency Flow (Hotspots)", diagram_type="dependency_flow",
                mermaid_code=build_dependency_flow_diagram(intelligence.dependency_hotspots, depends_on_edges),
            )
        )

    facts_lines = [
        f"repository_name={repository.name}", f"top_level_modules={dict(module_counts.most_common(10))}",
        f"total_dependency_edges={len(depends_on_edges)}",
    ]
    if intelligence is not None:
        facts_lines += [
            f"entry_points={intelligence.entry_points}", f"circular_dependencies={intelligence.circular_dependencies}",
            f"dependency_hotspots={intelligence.dependency_hotspots}",
        ]

    return GeneratedReport(
        title="Architecture Report",
        summary=f"{repository.name}'s architecture spans {len(module_counts)} top-level module(s) with {len(depends_on_edges)} resolved dependency edge(s).",
        sections=sections,
        diagrams=diagrams,
        ai_section_headings=["Architecture Narrative"],
        ai_facts_context="\n".join(facts_lines),
        ai_evidence_for_verification=evidence_for_verification_from_files(facts.file_paths),
    )
