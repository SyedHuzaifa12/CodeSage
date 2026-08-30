"""Query intent contracts — classification output, not the classifier itself.

The classifier lives in ``ai/engine/intent.py``; this module only
defines what it produces, so every other stage can depend on the
contract without depending on the (deterministic, rule-based)
implementation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class QueryIntent(str, Enum):
    """A repository question's category — drives retrieval-source tuning and prompt selection.

    Covers every category CLAUDE.md/the Sprint 5 spec names explicitly;
    ``GENERAL`` is the deliberate fallback for anything that doesn't
    match a more specific rule, not a failure state.
    """

    ARCHITECTURE_OVERVIEW = "architecture_overview"
    IMPLEMENTATION = "implementation"
    SYMBOL_LOOKUP = "symbol_lookup"
    DEPENDENCY_ANALYSIS = "dependency_analysis"
    CALL_RELATIONSHIPS = "call_relationships"
    IMPACT_ANALYSIS = "impact_analysis"
    DEBUGGING = "debugging"
    CONFIGURATION = "configuration"
    DATABASE_DATA_FLOW = "database_data_flow"
    TESTING = "testing"
    SECURITY = "security"
    GENERAL = "general"


@dataclass
class IntentAnalysis:
    """The result of classifying one query."""

    intent: QueryIntent
    matched_rules: list[str] = field(default_factory=list)
