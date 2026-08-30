"""Query / Intent Analysis — deterministic, rule-based (spec §2).

No LLM here by design: the spec explicitly warns against introducing
one "merely because it sounds more advanced", and every category below
is reliably identifiable from surface phrasing. If a genuinely
LLM-beneficial case is found later, ``classify_intent``'s signature is
the seam to swap behind — nothing upstream/downstream depends on *how*
classification happens, only on the ``IntentAnalysis`` it returns.
"""
from __future__ import annotations

from app.ai.schemas.intent import IntentAnalysis, QueryIntent

# Ordered rules — first match wins. Order matters: e.g. "where is
# authentication implemented" contains both an IMPLEMENTATION cue
# ("implemented") and a SYMBOL_LOOKUP cue ("where is"); IMPLEMENTATION
# is checked first because it yields the more useful prompt instruction
# (prioritize exact source) for that phrasing.
_RULES: list[tuple[QueryIntent, tuple[str, ...]]] = [
    (QueryIntent.CALL_RELATIONSHIPS, ("calls", "caller", "callee", "call graph", "who invokes", "invoke")),
    (QueryIntent.DEPENDENCY_ANALYSIS, ("depend", "dependency", "dependencies", "imports", "requires")),
    (QueryIntent.IMPACT_ANALYSIS, ("impact", "affect", "if i change", "if we change", "side effect", "break if")),
    (QueryIntent.TESTING, ("test", "tests", "testing", "spec", "coverage")),
    (QueryIntent.CONFIGURATION, ("config", "configuration", "settings", "environment variable", "env var", ".env")),
    # SECURITY is checked before DATABASE_DATA_FLOW: "sql injection vulnerability" would
    # otherwise match DATABASE_DATA_FLOW's generic "sql" keyword first.
    (QueryIntent.SECURITY, ("vulnerab", "insecure", "exploit", "injection", "sanitiz", "xss", "csrf", "security risk")),
    (QueryIntent.DATABASE_DATA_FLOW, ("database", "db connection", "data flow", "schema", "sql", "orm", "query the")),
    (QueryIntent.DEBUGGING, ("bug", "error", "exception", "crash", "traceback", "fails", "failing", "debug")),
    (QueryIntent.ARCHITECTURE_OVERVIEW, ("architecture", "overview", "high level", "high-level", "how is this organized", "structure of")),
    (QueryIntent.IMPLEMENTATION, ("implement", "how does", "how is", "logic for", "algorithm")),
    (QueryIntent.SYMBOL_LOOKUP, ("where is", "which function", "which class", "definition of", "locate", "find the")),
]


def classify_intent(normalized_query: str) -> IntentAnalysis:
    """Classify a normalized query into one of the repository-question categories.

    Args:
        normalized_query: The whitespace-normalized query text (see
            ``app.retrieval.utils.analyze_query`` — reused for
            normalization so intent classification and retrieval
            tokenization never disagree on what "the query" is).

    Returns:
        The matched intent, or ``QueryIntent.GENERAL`` if nothing matched.
    """
    lowered = normalized_query.lower()
    for intent, keywords in _RULES:
        matched = [kw for kw in keywords if kw in lowered]
        if matched:
            return IntentAnalysis(intent=intent, matched_rules=matched)
    return IntentAnalysis(intent=QueryIntent.GENERAL, matched_rules=[])
