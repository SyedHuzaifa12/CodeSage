"""Answer Formatter (spec §9) — the stable, structured response contract.

Also owns the "downgrade" behavior spec §8 requires: a
``CONTRADICTED``/``INSUFFICIENT_EVIDENCE`` result (after the bounded
verification retry is exhausted) is never returned as if it were a
normal answer — it's replaced with an honest, evidence-free statement,
while still surfacing whatever citations *did* verify.
"""
from __future__ import annotations

import uuid

from app.ai.graph.state import EvidenceWithText, LLMAnswer
from app.ai.schemas.dto import AskMetadata, AskResponseData, Citation, StageLatency, VerificationInfo
from app.ai.schemas.intent import QueryIntent
from app.ai.schemas.verification import VerificationResult, VerificationStatus

_NO_EVIDENCE_MESSAGE = "I don't have enough repository evidence to answer this question with confidence."
_CONTRADICTED_MESSAGE = (
    "I could not produce a reliably grounded answer to this question — my draft answer referenced "
    "information that doesn't match the retrieved repository evidence. Please try rephrasing the question "
    "or asking about a more specific file, symbol, or module."
)


def format_response(
    *, repository_id: uuid.UUID, query: str, intent: QueryIntent, llm_answer: LLMAnswer,
    evidence: list[EvidenceWithText], verification: VerificationResult, retry_count: int, cache_hit: bool,
    stage_latency_ms: dict[str, int], retrieval_candidates: int,
) -> AskResponseData:
    """Shape the final pipeline state into the stable API response contract.

    Args:
        repository_id: The repository that was queried.
        query: The user's original question.
        intent: The classified intent.
        llm_answer: The (possibly empty, if short-circuited before
            reasoning) raw LLM completion.
        evidence: The evidence actually used to build the context.
        verification: The verification gate's final outcome.
        retry_count: How many verification-triggered retries ran.
        cache_hit: Whether this response was served from the AI answer cache.
        stage_latency_ms: Per-stage timings.
        retrieval_candidates: Total candidates retrieval produced (pre-selection), for observability.

    Returns:
        The complete, stable response contract.
    """
    answer_text = llm_answer.get("text", "") if llm_answer else ""
    if verification.status == VerificationStatus.CONTRADICTED:
        answer_text = _CONTRADICTED_MESSAGE
    elif verification.status == VerificationStatus.INSUFFICIENT_EVIDENCE and not answer_text:
        answer_text = _NO_EVIDENCE_MESSAGE

    citations = [
        Citation(
            file_path=item["file_path"], symbol_name=item.get("symbol_name"), symbol_type=item.get("symbol_type"),
            start_line=item.get("start_line"), end_line=item.get("end_line"),
            retrieval_score=item["retrieval_score"], retrieval_sources=item["retrieval_sources"],
        )
        for item in evidence
    ]
    relevant_files = sorted({item["file_path"] for item in evidence})
    relevant_symbols = sorted({item["symbol_name"] for item in evidence if item.get("symbol_name")})

    return AskResponseData(
        repository_id=repository_id,
        query=query,
        answer=answer_text,
        explanation=None,
        evidence=citations,
        relevant_files=relevant_files,
        relevant_symbols=relevant_symbols,
        verification=VerificationInfo(status=verification.status.value, reasons=verification.reasons),
        metadata=AskMetadata(
            intent=intent.value,
            provider=llm_answer.get("provider", "") if llm_answer else "",
            model=llm_answer.get("model", "") if llm_answer else "",
            cache_hit=cache_hit,
            retry_count=retry_count,
            stage_latency_ms=StageLatency(
                intent_ms=stage_latency_ms.get("intent", 0),
                retrieval_ms=stage_latency_ms.get("retrieval", 0),
                evidence_selection_ms=stage_latency_ms.get("evidence_selection", 0),
                context_construction_ms=stage_latency_ms.get("context_construction", 0),
                llm_ms=stage_latency_ms.get("llm", 0),
                verification_ms=stage_latency_ms.get("verification", 0),
                formatting_ms=stage_latency_ms.get("formatting", 0),
                total_ms=sum(stage_latency_ms.values()),
            ),
            retrieval_candidates=retrieval_candidates,
            prompt_tokens=llm_answer.get("prompt_tokens") if llm_answer else None,
            completion_tokens=llm_answer.get("completion_tokens") if llm_answer else None,
        ),
    )
