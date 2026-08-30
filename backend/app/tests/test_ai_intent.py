"""Unit tests for deterministic query-intent classification (Sprint 5)."""
from __future__ import annotations

from app.ai.engine.intent import classify_intent
from app.ai.schemas.intent import QueryIntent


class TestClassifyIntent:
    def test_call_relationships(self) -> None:
        assert classify_intent("what calls getUserById?").intent == QueryIntent.CALL_RELATIONSHIPS

    def test_dependency_analysis(self) -> None:
        assert classify_intent("which modules depend on the auth package?").intent == QueryIntent.DEPENDENCY_ANALYSIS

    def test_impact_analysis(self) -> None:
        assert classify_intent("what would be the impact of changing User.save?").intent == QueryIntent.IMPACT_ANALYSIS

    def test_testing(self) -> None:
        assert classify_intent("which tests cover authentication?").intent == QueryIntent.TESTING

    def test_configuration(self) -> None:
        assert classify_intent("where is the database configuration?").intent == QueryIntent.CONFIGURATION

    def test_database_data_flow(self) -> None:
        assert classify_intent("how is the database connection established?").intent == QueryIntent.DATABASE_DATA_FLOW

    def test_debugging(self) -> None:
        assert classify_intent("why does login throw an exception?").intent == QueryIntent.DEBUGGING

    def test_security(self) -> None:
        assert classify_intent("is there a sql injection vulnerability here?").intent == QueryIntent.SECURITY

    def test_architecture_overview(self) -> None:
        assert classify_intent("give me a high level overview of the architecture").intent == QueryIntent.ARCHITECTURE_OVERVIEW

    def test_implementation(self) -> None:
        assert classify_intent("how is password hashing implemented?").intent == QueryIntent.IMPLEMENTATION

    def test_symbol_lookup(self) -> None:
        assert classify_intent("where is the PaymentRepository class defined?").intent == QueryIntent.SYMBOL_LOOKUP

    def test_general_fallback(self) -> None:
        assert classify_intent("hello there").intent == QueryIntent.GENERAL

    def test_implementation_wins_over_symbol_lookup_when_both_match(self) -> None:
        """'where is X implemented' should prioritize source-heavy IMPLEMENTATION over bare SYMBOL_LOOKUP."""
        assert classify_intent("where is authentication implemented?").intent == QueryIntent.IMPLEMENTATION

    def test_matched_rules_are_recorded(self) -> None:
        result = classify_intent("what calls the login function?")
        assert "calls" in result.matched_rules

    def test_is_case_insensitive(self) -> None:
        assert classify_intent("WHAT CALLS getUserById?").intent == QueryIntent.CALL_RELATIONSHIPS
