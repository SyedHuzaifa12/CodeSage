"""Full-graph orchestrator tests — fake LLM/retrieval, no real infra (spec §17: never a real paid LLM in unit tests).

Exercises the actual compiled LangGraph pipeline end-to-end, including
the bounded verification-retry loop, purely against monkeypatched
stage dependencies.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

import app.ai.engine.orchestrator as orchestrator
from app.ai.engine.orchestrator import run_pipeline
from app.ai.llm.provider import LLMCompletion
from app.ai.schemas.verification import VerificationStatus
from app.core.config import Settings
from app.models.repository import Repository
from app.retrieval.schemas import EvidenceResult, RetrievalQueryData, RetrievalStats

REPO = uuid.uuid4()


def make_retrieval_result(evidence: list[EvidenceResult]) -> RetrievalQueryData:
    return RetrievalQueryData(
        repository_id=REPO, query="q", top_k=10, sources_requested=["semantic"], results=evidence,
        stats=RetrievalStats(
            candidates_semantic=len(evidence), candidates_lexical=0, candidates_structural=0,
            candidates_after_dedup=len(evidence), stage_latency_ms={}, total_latency_ms=1,
            cache_hit=False, sources_failed=[],
        ),
    )


def make_evidence(file_path: str, symbol_name: str, score: float = 0.9) -> EvidenceResult:
    return EvidenceResult(
        rank=1, final_score=score, repository_id=REPO, file_id=uuid.uuid4(), file_path=file_path,
        chunk_id=None, symbol_id=None, symbol_name=symbol_name, qualified_name=None, symbol_type="function",
        start_line=1, end_line=2, language="Python", sources=["semantic"], source_scores=[], reasons=[],
    )


def make_initial_state(repository: Repository, query: str = "how is auth implemented") -> dict:
    return {
        "request_id": "test-request", "repository_id": REPO, "repository": repository, "query": query,
        "top_k_override": None, "sources_override": None, "session": None, "settings": Settings(),
        "retry_count": 0, "force_insufficient": False, "stage_latency_ms": {},
    }


@pytest.fixture(autouse=True)
def _fake_intelligence(monkeypatch: pytest.MonkeyPatch):
    async def fake_get_intelligence(session, repository_id):
        return None

    monkeypatch.setattr(orchestrator.ingestion_db, "get_intelligence", fake_get_intelligence)


class TestFullPipelineHappyPath:
    async def test_grounded_answer_is_supported(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "auth.py").write_text("def authenticate_user():\n    return True\n")
        repository = Repository(id=REPO, name="r", local_path=str(tmp_path), status="ready")
        evidence = [make_evidence("auth.py", "authenticate_user")]

        async def fake_retrieve_evidence(**kwargs):
            return make_retrieval_result(evidence)

        async def fake_generate_answer(**kwargs):
            return LLMCompletion(text="Authentication is handled by authenticate_user() in auth.py.", provider="fake", model="fake-model")

        monkeypatch.setattr(orchestrator, "retrieve_evidence", fake_retrieve_evidence)
        monkeypatch.setattr(orchestrator, "generate_answer", fake_generate_answer)

        final_state = await run_pipeline(make_initial_state(repository))
        response = final_state["final_response"]

        assert response.verification.status == VerificationStatus.SUPPORTED.value
        assert "authenticate_user" in response.answer
        assert response.metadata.retry_count == 0
        assert len(response.evidence) == 1
        assert response.evidence[0].file_path == "auth.py"

    async def test_empty_evidence_short_circuits_before_calling_llm(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repository = Repository(id=REPO, name="r", local_path=str(tmp_path), status="ready")
        llm_called = False

        async def fake_retrieve_evidence(**kwargs):
            return make_retrieval_result([])

        async def fake_generate_answer(**kwargs):
            nonlocal llm_called
            llm_called = True
            return LLMCompletion(text="should never be reached", provider="fake", model="fake-model")

        monkeypatch.setattr(orchestrator, "retrieve_evidence", fake_retrieve_evidence)
        monkeypatch.setattr(orchestrator, "generate_answer", fake_generate_answer)

        final_state = await run_pipeline(make_initial_state(repository))
        response = final_state["final_response"]

        assert llm_called is False
        assert response.verification.status == VerificationStatus.INSUFFICIENT_EVIDENCE.value


class TestVerificationRetryLoop:
    async def test_contradicted_answer_triggers_one_broadened_retry(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "auth.py").write_text("def authenticate_user():\n    return True\n")
        repository = Repository(id=REPO, name="r", local_path=str(tmp_path), status="ready")
        evidence = [make_evidence("auth.py", "authenticate_user")]
        retrieval_call_count = 0
        reasoning_call_count = 0

        async def fake_retrieve_evidence(**kwargs):
            nonlocal retrieval_call_count
            retrieval_call_count += 1
            return make_retrieval_result(evidence)

        async def fake_generate_answer(**kwargs):
            nonlocal reasoning_call_count
            reasoning_call_count += 1
            if reasoning_call_count == 1:
                return LLMCompletion(text="See fabricated_module.py for the answer.", provider="fake", model="fake-model")
            return LLMCompletion(text="Authentication is handled by authenticate_user() in auth.py.", provider="fake", model="fake-model")

        monkeypatch.setattr(orchestrator, "retrieve_evidence", fake_retrieve_evidence)
        monkeypatch.setattr(orchestrator, "generate_answer", fake_generate_answer)

        final_state = await run_pipeline(make_initial_state(repository))
        response = final_state["final_response"]

        assert retrieval_call_count == 2  # initial + one bounded retry
        assert reasoning_call_count == 2
        assert response.metadata.retry_count == 1
        assert response.verification.status == VerificationStatus.SUPPORTED.value

    async def test_retry_is_strictly_bounded_and_downgrades_on_final_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Even if every attempt is contradicted, the loop must terminate — never an unbounded agent loop."""
        (tmp_path / "auth.py").write_text("def authenticate_user():\n    return True\n")
        repository = Repository(id=REPO, name="r", local_path=str(tmp_path), status="ready")
        evidence = [make_evidence("auth.py", "authenticate_user")]
        reasoning_call_count = 0

        async def fake_retrieve_evidence(**kwargs):
            return make_retrieval_result(evidence)

        async def fake_generate_answer(**kwargs):
            nonlocal reasoning_call_count
            reasoning_call_count += 1
            return LLMCompletion(text="See totally_fabricated_file.py.", provider="fake", model="fake-model")

        monkeypatch.setattr(orchestrator, "retrieve_evidence", fake_retrieve_evidence)
        monkeypatch.setattr(orchestrator, "generate_answer", fake_generate_answer)

        cfg = Settings()
        assert cfg.ai.max_verification_retries == 1  # the configured ceiling this test asserts against

        initial_state = make_initial_state(repository)
        initial_state["settings"] = cfg
        final_state = await run_pipeline(initial_state)
        response = final_state["final_response"]

        assert reasoning_call_count == cfg.ai.max_verification_retries + 1
        assert response.metadata.retry_count == cfg.ai.max_verification_retries
        assert response.verification.status == VerificationStatus.CONTRADICTED.value
        assert "totally_fabricated_file.py" not in response.answer  # the downgraded answer never repeats the fabrication
