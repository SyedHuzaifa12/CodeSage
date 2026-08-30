"""Dependency & Risk Report generator (spec §5) — internal type ``dependency_risk``.

Deterministic-only by design (no AI narrative section): every fact here
is a direct count or list from ``RepositoryIntelligence``/relationships,
and risk classification is a simple, explainable threshold rule over
those counts — spec §9 explicitly discourages an LLM call where
deterministic generation is already sufficient, and spec §5 requires
risk classification to be evidence-based, not a security-scanner
judgment call an LLM might overstate.
"""
from __future__ import annotations

from app.reports.evidence import intelligence_evidence, relationship_evidence
from app.reports.generators import GeneratedReport, RepositoryFacts
from app.reports.schemas import EvidenceConfidence, ReportSection

# A module qualifies as "high risk" purely by evidence-backed structural
# signals: many incoming dependents (a change ripples widely) or
# participation in a circular dependency chain (bidirectional coupling).
# Deliberately not a security/correctness judgment (spec §5: "this
# sprint is not a replacement for a dedicated security scanner").
_HIGH_RISK_INCOMING_THRESHOLD = 5


def _classify_risk(module_path: str, incoming: int, cyclic_modules: set[str]) -> str:
    if module_path in cyclic_modules and incoming >= _HIGH_RISK_INCOMING_THRESHOLD:
        return "high"
    if module_path in cyclic_modules or incoming >= _HIGH_RISK_INCOMING_THRESHOLD:
        return "medium"
    return "low"


def generate(facts: RepositoryFacts) -> GeneratedReport:
    """Build the deterministic Dependency & Risk Report.

    Args:
        facts: Already-collected repository data.

    Returns:
        The generator's deterministic output (no AI section headings —
        this report type stays fully deterministic).
    """
    repository = facts.repository
    intelligence = facts.intelligence
    depends_on_edges = facts.depends_on_edges

    sections: list[ReportSection] = []
    cyclic_modules: set[str] = set()

    if intelligence is not None:
        hotspots = intelligence.dependency_hotspots or []
        cyclic_modules = {module for cycle in intelligence.circular_dependencies for module in cycle}

        risk_rows = [
            {
                "module_path": h["module_path"], "incoming_dependencies": h["incoming_dependencies"],
                "risk": _classify_risk(h["module_path"], h["incoming_dependencies"], cyclic_modules),
            }
            for h in hotspots
        ]
        high_risk = [r for r in risk_rows if r["risk"] == "high"]

        sections.append(
            ReportSection(
                heading="Dependency Hotspots",
                content=(
                    "Modules ranked by incoming dependency count: "
                    + ", ".join(f"{r['module_path']} ({r['incoming_dependencies']}, risk={r['risk']})" for r in risk_rows)
                ) if risk_rows else "No dependency hotspots were detected.",
                confidence=EvidenceConfidence.VERIFIED,
                evidence=[intelligence_evidence("dependency_hotspots", f"{r['module_path']}: {r['incoming_dependencies']} incoming dependencies") for r in risk_rows],
                metrics={"hotspots": risk_rows},
                findings=[f"{r['module_path']} is high-risk (heavily depended-on and part of a dependency cycle)." for r in high_risk],
            )
        )

        if intelligence.circular_dependencies:
            cycle_descriptions = [" -> ".join(cycle) for cycle in intelligence.circular_dependencies]
            sections.append(
                ReportSection(
                    heading="Circular Dependencies",
                    content=f"{len(intelligence.circular_dependencies)} circular dependency chain(s) detected: " + "; ".join(cycle_descriptions),
                    confidence=EvidenceConfidence.VERIFIED,
                    evidence=[intelligence_evidence("circular_dependencies", desc) for desc in cycle_descriptions],
                    findings=cycle_descriptions,
                )
            )
        else:
            sections.append(
                ReportSection(
                    heading="Circular Dependencies",
                    content="No circular dependencies were detected.",
                    confidence=EvidenceConfidence.VERIFIED,
                )
            )

        orphans = intelligence.orphan_files or []
        sections.append(
            ReportSection(
                heading="Orphan Files",
                content=(
                    f"{len(orphans)} file(s) are never imported/depended on by any other resolved file: " + ", ".join(orphans[:15])
                ) if orphans else "No orphan files were detected.",
                confidence=EvidenceConfidence.VERIFIED,
                evidence=[intelligence_evidence("orphan_files", path) for path in orphans[:10]],
                findings=orphans,
            )
        )
    else:
        sections.append(
            ReportSection(
                heading="Dependency Hotspots",
                content="Repository intelligence has not been computed yet — dependency/risk analysis is unavailable.",
                confidence=EvidenceConfidence.INSUFFICIENT_EVIDENCE,
            )
        )

    calls_edges = facts.calls_edges
    if calls_edges:
        callee_counts: dict[str, int] = {}
        for edge in calls_edges:
            callee_counts[edge.target_symbol] = callee_counts.get(edge.target_symbol, 0) + 1
        most_called = sorted(callee_counts.items(), key=lambda kv: -kv[1])[:10]
        sections.append(
            ReportSection(
                heading="Call Relationships",
                content=(
                    "Most-called symbols: " + ", ".join(f"{name} ({count} caller(s))" for name, count in most_called)
                ) if most_called else "No call-graph edges were found.",
                confidence=EvidenceConfidence.VERIFIED,
                evidence=[relationship_evidence(edge.source_symbol, edge.target_symbol, "calls") for edge in calls_edges[:10]],
                metrics={"total_call_edges": len(calls_edges)},
            )
        )

    high_risk_count = sum(1 for s in sections if s.heading == "Dependency Hotspots" for _ in s.findings)
    summary = (
        f"{repository.name}: {len(depends_on_edges)} dependency edge(s), "
        f"{len(intelligence.circular_dependencies) if intelligence else 0} circular dependency chain(s), "
        f"{len(intelligence.orphan_files) if intelligence else 0} orphan file(s), {high_risk_count} high-risk module(s)."
    )

    return GeneratedReport(title="Dependency & Risk Report", summary=summary, sections=sections)
