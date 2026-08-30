"""Unit tests for AI report synthesis using a FakeLLMProvider — no real LLM call (spec §20).

Covers grounded synthesis, insufficient evidence, malformed JSON output,
and verification (partial-support) failures — all deterministic.
"""
from __future__ import annotations

import pytest

from app.ai.llm.provider import LLMCompletion
from app.core.config import LLMSettings
from app.reports.generators import evidence_for_verification_from_files
from app.reports.schemas import EvidenceConfidence
from app.reports import synthesis as synthesis_module


class _StubProvider:
    provider_name = "fake"
    model = "fake-model"


@pytest.fixture(autouse=True)
def _patch_provider(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(synthesis_module, "get_llm_provider", lambda: _StubProvider())
    yield


def _patch_completion(monkeypatch: pytest.MonkeyPatch, text: str | None = None, raises: Exception | None = None):
    async def fake_complete_with_retry(provider, system_prompt, user_prompt, settings):
        if raises is not None:
            raise raises
        return LLMCompletion(text=text or "", provider="fake", model="fake-model")

    monkeypatch.setattr(synthesis_module, "complete_with_retry", fake_complete_with_retry)


class TestGroundedSynthesis:
    async def test_valid_json_with_grounded_citations_is_derived(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_completion(
            monkeypatch,
            text='{"summary": "A small repo.", "sections": {"Narrative Overview": "See app/main.py for the entry point."}}',
        )
        result = await synthesis_module.synthesize_report_narrative(
            facts_context="entry_points=['app/main.py']", section_headings=["Narrative Overview"],
            evidence_for_verification=evidence_for_verification_from_files(["app/main.py"]),
            llm_settings=LLMSettings(),
        )
        assert result.ai_used is True
        assert result.ai_synthesis_failed is False
        assert result.summary == "A small repo."
        assert result.sections["Narrative Overview"].confidence == EvidenceConfidence.DERIVED


class TestInsufficientEvidence:
    async def test_fabricated_citation_is_flagged_insufficient(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_completion(
            monkeypatch,
            text='{"summary": "", "sections": {"Narrative Overview": "See app/nonexistent_module.py for details."}}',
        )
        result = await synthesis_module.synthesize_report_narrative(
            facts_context="entry_points=['app/main.py']", section_headings=["Narrative Overview"],
            evidence_for_verification=evidence_for_verification_from_files(["app/main.py"]),
            llm_settings=LLMSettings(),
        )
        assert result.ai_synthesis_failed is False
        assert result.sections["Narrative Overview"].confidence == EvidenceConfidence.INSUFFICIENT_EVIDENCE


class TestPartialVerification:
    async def test_mixed_citations_are_partial(self, monkeypatch: pytest.MonkeyPatch) -> None:
        text = (
            '{"summary": "", "sections": {"Narrative Overview": '
            '"See app/main.py and app/nonexistent.py for details."}}'
        )
        _patch_completion(monkeypatch, text=text)
        result = await synthesis_module.synthesize_report_narrative(
            facts_context="x", section_headings=["Narrative Overview"],
            evidence_for_verification=evidence_for_verification_from_files(["app/main.py"]),
            llm_settings=LLMSettings(),
        )
        assert result.sections["Narrative Overview"].confidence == EvidenceConfidence.PARTIAL


class TestMalformedOutput:
    async def test_non_json_output_falls_back_gracefully(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_completion(monkeypatch, text="I'm sorry, here is a prose answer with no JSON at all.")
        result = await synthesis_module.synthesize_report_narrative(
            facts_context="x", section_headings=["Narrative Overview"],
            evidence_for_verification=[], llm_settings=LLMSettings(),
        )
        assert result.ai_synthesis_failed is True
        assert result.sections == {}

    async def test_json_missing_sections_key_falls_back_gracefully(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_completion(monkeypatch, text='{"summary": "no sections field here"}')
        result = await synthesis_module.synthesize_report_narrative(
            facts_context="x", section_headings=["Narrative Overview"],
            evidence_for_verification=[], llm_settings=LLMSettings(),
        )
        assert result.ai_synthesis_failed is False  # 'sections' defaults to {} — a valid, if empty, result
        assert result.sections == {}


class TestProviderFailure:
    async def test_provider_exception_falls_back_gracefully(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_completion(monkeypatch, raises=RuntimeError("provider unavailable"))
        result = await synthesis_module.synthesize_report_narrative(
            facts_context="x", section_headings=["Narrative Overview"],
            evidence_for_verification=[], llm_settings=LLMSettings(),
        )
        assert result.ai_synthesis_failed is True
        assert result.failure_reason
