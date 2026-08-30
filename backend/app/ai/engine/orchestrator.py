"""The AI Engine orchestrator — the single entry point coordinating every stage (spec §1/§19).

This is the ONLY file in the codebase that imports LangGraph. Every
other ``ai/engine/*.py`` stage is a plain async function with no
orchestration-framework dependency — if the orchestration layer ever
changed, only this file would need to.

    intent -> retrieval -> evidence_selection -> context_construction
        -> reasoning -> verification -[bounded retry]-> retrieval
        -> ... -> formatting

The only loop in the graph is the bounded verification retry
(spec §19: "every loop must have a strict maximum iteration limit");
there is no other conditional branching and no open-ended agent
behavior.
"""
from __future__ import annotations

import logging
import time

from langgraph.graph import END, START, StateGraph

from app.ai.engine.context import build_context, select_evidence
from app.ai.engine.formatter import format_response
from app.ai.engine.intent import classify_intent
from app.ai.engine.reasoning import generate_answer
from app.ai.engine.retrieval import retrieve_evidence
from app.ai.engine.verification import pre_check_evidence_sufficiency, verify_answer
from app.ai.graph.state import AIGraphState
from app.ai.schemas.verification import VerificationResult, VerificationStatus
from app.ingestion import repository as ingestion_db
from app.retrieval.utils import analyze_query

logger = logging.getLogger("codesage.ai.engine.orchestrator")


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _record(state: AIGraphState, stage: str, started: float) -> dict[str, int]:
    latencies = dict(state.get("stage_latency_ms", {}))
    latencies[stage] = latencies.get(stage, 0) + _elapsed_ms(started)
    return latencies


async def _intent_node(state: AIGraphState) -> dict:
    started = time.perf_counter()
    analysis = analyze_query(state["query"])
    intent = classify_intent(analysis.normalized)
    logger.info("AI intent classified: %s (matched=%s)", intent.intent.value, intent.matched_rules)
    return {"intent": intent, "stage_latency_ms": _record(state, "intent", started)}


async def _retrieval_node(state: AIGraphState) -> dict:
    started = time.perf_counter()
    retry_count = state.get("retry_count", 0)
    result = await retrieve_evidence(
        session=state["session"], settings=state["settings"], repository_id=state["repository_id"],
        query=state["query"], intent=state["intent"].intent, top_k_override=state.get("top_k_override"),
        sources_override=state.get("sources_override"), broaden=retry_count > 0,
    )
    return {"retrieval_result": result, "stage_latency_ms": _record(state, "retrieval", started)}


async def _evidence_selection_node(state: AIGraphState) -> dict:
    started = time.perf_counter()
    cfg = state["settings"].ai
    selected = select_evidence(state["retrieval_result"].results, state["intent"].intent, cfg)
    update: dict = {"selected_results": selected, "stage_latency_ms": _record(state, "evidence_selection", started)}

    pre_check = pre_check_evidence_sufficiency(selected, cfg)
    if pre_check is not None:
        update["verification"] = pre_check
        update["force_insufficient"] = True
    return update


async def _context_construction_node(state: AIGraphState) -> dict:
    started = time.perf_counter()
    if state.get("force_insufficient"):
        return {"selected_evidence": [], "context_text": "", "stage_latency_ms": _record(state, "context_construction", started)}

    cfg = state["settings"].ai
    intelligence = await ingestion_db.get_intelligence(state["session"], state["repository_id"])
    context_text, enriched = build_context(state["repository"], state["selected_results"], state["intent"].intent, cfg, intelligence)
    return {
        "selected_evidence": enriched, "context_text": context_text,
        "stage_latency_ms": _record(state, "context_construction", started),
    }


async def _reasoning_node(state: AIGraphState) -> dict:
    started = time.perf_counter()
    if state.get("force_insufficient"):
        return {"llm_answer": {}, "stage_latency_ms": _record(state, "llm", started)}

    completion = await generate_answer(
        llm_settings=state["settings"].llm, intent=state["intent"].intent,
        context_text=state["context_text"], query=state["query"], is_retry=state.get("retry_count", 0) > 0,
    )
    llm_answer = {
        "text": completion.text, "provider": completion.provider, "model": completion.model,
        "prompt_tokens": completion.prompt_tokens, "completion_tokens": completion.completion_tokens,
    }
    return {"llm_answer": llm_answer, "stage_latency_ms": _record(state, "llm", started)}


async def _verification_node(state: AIGraphState) -> dict:
    started = time.perf_counter()
    if state.get("force_insufficient"):
        # Already set by _evidence_selection_node's pre-check — nothing new to verify.
        return {"stage_latency_ms": _record(state, "verification", started)}

    result = verify_answer(state.get("llm_answer", {}).get("text", ""), state.get("selected_evidence", []))
    return {"verification": result, "stage_latency_ms": _record(state, "verification", started)}


def _route_after_verification(state: AIGraphState) -> str:
    """Bounded conditional edge (spec §19): retry once, broadened, on a failed verification."""
    verification: VerificationResult = state["verification"]
    cfg = state["settings"].ai
    retry_count = state.get("retry_count", 0)
    if verification.is_acceptable or state.get("force_insufficient") or retry_count >= cfg.max_verification_retries:
        return "formatting"
    logger.info("Verification %s with retries remaining (%d/%d) — retrying with broadened retrieval", verification.status.value, retry_count, cfg.max_verification_retries)
    return "retry"


async def _increment_retry_node(state: AIGraphState) -> dict:
    return {"retry_count": state.get("retry_count", 0) + 1}


async def _formatting_node(state: AIGraphState) -> dict:
    started = time.perf_counter()
    verification = state.get("verification") or VerificationResult(status=VerificationStatus.INSUFFICIENT_EVIDENCE, reasons=["No verification was performed."])
    response = format_response(
        repository_id=state["repository_id"], query=state["query"], intent=state["intent"].intent,
        llm_answer=state.get("llm_answer", {}), evidence=state.get("selected_evidence", []), verification=verification,
        retry_count=state.get("retry_count", 0), cache_hit=False, stage_latency_ms=state.get("stage_latency_ms", {}),
        retrieval_candidates=(
            state["retrieval_result"].stats.candidates_semantic
            + state["retrieval_result"].stats.candidates_lexical
            + state["retrieval_result"].stats.candidates_structural
        ) if state.get("retrieval_result") else 0,
    )
    latencies = _record(state, "formatting", started)
    response.metadata.stage_latency_ms.formatting_ms = latencies.get("formatting", 0)
    response.metadata.stage_latency_ms.total_ms = sum(latencies.values())
    return {"final_response": response, "stage_latency_ms": latencies}


_compiled_graph = None


def _build_graph():
    """Build and compile the LangGraph state machine. Called once, lazily, on first use."""
    graph = StateGraph(AIGraphState)
    graph.add_node("intent", _intent_node)
    graph.add_node("retrieval", _retrieval_node)
    graph.add_node("evidence_selection", _evidence_selection_node)
    graph.add_node("context_construction", _context_construction_node)
    graph.add_node("reasoning", _reasoning_node)
    graph.add_node("verification", _verification_node)
    graph.add_node("retry", _increment_retry_node)
    graph.add_node("formatting", _formatting_node)

    graph.add_edge(START, "intent")
    graph.add_edge("intent", "retrieval")
    graph.add_edge("retrieval", "evidence_selection")
    graph.add_edge("evidence_selection", "context_construction")
    graph.add_edge("context_construction", "reasoning")
    graph.add_edge("reasoning", "verification")
    graph.add_conditional_edges("verification", _route_after_verification, {"formatting": "formatting", "retry": "retry"})
    graph.add_edge("retry", "retrieval")
    graph.add_edge("formatting", END)
    return graph.compile()


def get_compiled_graph():
    """Return the process-wide compiled graph, building it on first use.

    Returns:
        The compiled LangGraph application.
    """
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = _build_graph()
    return _compiled_graph


async def run_pipeline(initial_state: AIGraphState) -> AIGraphState:
    """Run the full AI pipeline for one request.

    Args:
        initial_state: The seeded state (repository, query, session,
            settings, request_id — see ``ai/services/ai_service.py``).

    Returns:
        The final state, including ``final_response``.
    """
    graph = get_compiled_graph()
    return await graph.ainvoke(initial_state)
