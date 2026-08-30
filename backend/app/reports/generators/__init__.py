"""Report generators — one deterministic-data-collection module per report type.

Every generator function has the same shape:
``def generate(facts: RepositoryFacts) -> GeneratedReport`` — pure,
synchronous, and given already-fetched data (spec §3: "reuse existing
data, do not recompute intelligence"; no generator ever queries a
database, calls Tree-sitter, or generates embeddings itself). The
optional AI-narrative step is layered on afterward, uniformly, by
``reports/service.py`` — no generator calls the LLM directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.ai.graph.state import EvidenceWithText
from app.models.file import File
from app.models.relationship import Relationship
from app.models.repository import Repository
from app.models.repository_intelligence import RepositoryIntelligence
from app.models.symbol import Symbol
from app.reports.schemas import ReportDiagram, ReportSection


@dataclass
class RepositoryFacts:
    """Every already-parsed/analyzed piece of repository data a generator might need.

    Collected once per report generation (``reports/service.py``) and
    handed to whichever generator is running — never re-queried per
    generator, and never re-derived (Sprint 2A/2B's parsing/analysis is
    reused verbatim, per spec §3).
    """

    repository: Repository
    intelligence: Optional[RepositoryIntelligence]
    files: list[File]
    symbols: list[Symbol]
    relationships: list[Relationship]

    @property
    def depends_on_edges(self) -> list[tuple[str, str]]:
        """Resolved module-level ``depends_on`` edges, as ``(source, target)`` pairs."""
        return [(r.source_symbol, r.target_symbol) for r in self.relationships if r.relationship_type == "depends_on"]

    @property
    def calls_edges(self) -> list[Relationship]:
        """Call-graph edges (``relationship_type == "calls"``)."""
        return [r for r in self.relationships if r.relationship_type == "calls"]

    @property
    def import_edges(self) -> list[Relationship]:
        """Raw import-graph edges (``relationship_type == "imports"``), pre-resolution."""
        return [r for r in self.relationships if r.relationship_type == "imports"]

    @property
    def file_paths(self) -> list[str]:
        """Every file's repository-relative path."""
        return [f.path for f in self.files]


@dataclass
class GeneratedReport:
    """One generator's deterministic output, before any optional AI narrative pass."""

    title: str
    summary: str
    sections: list[ReportSection] = field(default_factory=list)
    diagrams: list[ReportDiagram] = field(default_factory=list)
    ai_section_headings: list[str] = field(default_factory=list)
    ai_facts_context: str = ""
    ai_evidence_for_verification: list[EvidenceWithText] = field(default_factory=list)


def evidence_for_verification_from_files(file_paths: list[str]) -> list[EvidenceWithText]:
    """Build a minimal evidence set (file paths only) for grounding-checking AI narrative.

    Args:
        file_paths: Real file paths the AI is allowed to cite.

    Returns:
        One ``EvidenceWithText`` entry per file, with no symbol/line
        information — sufficient for ``verify_answer``'s file-path
        citation check, which is the primary signal report narratives
        are checked against (reports rarely cite exact line ranges the
        way a Sprint 5 answer does).
    """
    return [
        EvidenceWithText(
            file_path=path, symbol_name=None, symbol_type=None, start_line=None, end_line=None,
            retrieval_score=1.0, retrieval_sources=["repository_intelligence"], text=None,
        )
        for path in file_paths
    ]
