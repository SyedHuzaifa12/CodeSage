"""CodeSage AI Engine Evaluation — Sprint 5.

Extends ``retrieval_eval.py``'s exact pattern (same fixture style, same
Recall@K/MRR metrics) to the full ``/ask`` pipeline, adding the
AI-specific dimensions spec §18 asks for:

- **Recall@K / MRR** — same definition as ``retrieval_eval.py``, computed
  over the response's ``evidence``/``relevant_files`` (the exact
  evidence the answer was grounded in, not raw retrieval candidates).
- **Groundedness** — the verification gate's status (``supported``/
  ``partially_supported`` counted as grounded; ``contradicted`` is not;
  ``insufficient_evidence`` is reported separately, since declining to
  answer is correct behavior, not a groundedness failure).
- **Citation accuracy** — same expected-path check as retrieval, applied
  to the answer's actual cited evidence.
- **Latency** — cold vs. warm (cache-hit) total latency.
- **Token/context usage** — prompt/completion token counts, where the
  provider reports them.

Not a claim that Sprint 5 is "good" merely because it returns answers
— every question here has a concrete, checkable expected outcome.
Deliberately not optimized for this one fixture (spec §18: "do not
optimize blindly for one test set") — it exists to make regressions
visible, not to be maximized.

Usage (from the backend/ directory, against a running Docker stack
with the target repository already fully indexed, AI-ready):

    python scripts/ai_eval.py --repository-id <uuid>
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from dataclasses import dataclass, field

import httpx


@dataclass
class AIEvalQuestion:
    """One evaluation question: a query and the file path(s) that should ground the answer."""

    question: str
    expected_path_substrings: list[str]
    expect_answerable: bool = True  # False for a deliberately unanswerable question


DEFAULT_FIXTURE: list[AIEvalQuestion] = [
    AIEvalQuestion("Where is authentication implemented?", ["app/auth/", "app/api/auth.py"]),
    AIEvalQuestion("Which files implement the User model?", ["app/models.py"]),
    AIEvalQuestion("Where is the database connection configured?", ["config.py", "app/__init__.py"]),
    AIEvalQuestion("Which tests are related to authentication?", ["tests.py"]),
    AIEvalQuestion("Where should a change to the login form be made?", ["app/auth/forms.py", "app/auth/routes.py"]),
    AIEvalQuestion("Where is email sending implemented?", ["app/auth/email.py", "app/email.py"]),
    AIEvalQuestion("How are errors handled?", ["app/errors", "app/api/errors.py"]),
    AIEvalQuestion(
        "What is the capital of France and how does that relate to quantum physics?",
        [], expect_answerable=False,
    ),
]


@dataclass
class AIQuestionResult:
    question: str
    hit: bool
    reciprocal_rank: float
    grounded: bool
    verification_status: str
    correctly_declined: bool  # True if an unanswerable question correctly returned insufficient_evidence
    latency_ms: float
    prompt_tokens: int | None
    completion_tokens: int | None
    cited_files: list[str] = field(default_factory=list)


def _first_hit_rank(paths: list[str], expected_substrings: list[str]) -> int:
    for rank, path in enumerate(paths, start=1):
        if any(substring in path for substring in expected_substrings):
            return rank
    return 0


def run_question(client: httpx.Client, repository_id: str, question: AIEvalQuestion, force_refresh: bool) -> AIQuestionResult:
    """Run one evaluation question against the real ``/ask`` endpoint and score it.

    Args:
        client: An open HTTP client against the backend.
        repository_id: The repository to query.
        question: The question to run.
        force_refresh: Whether to bypass the AI answer cache for this call.

    Returns:
        The scored result.
    """
    body = {"query": question.question, "options": {"force_refresh": force_refresh}}
    started = time.perf_counter()
    response = client.post(f"/api/v1/repositories/{repository_id}/ask", json=body)
    latency_ms = (time.perf_counter() - started) * 1000
    response.raise_for_status()
    data = response.json()["data"]

    verification_status = data["verification"]["status"]
    cited_files = data["relevant_files"]
    rank = _first_hit_rank(cited_files, question.expected_path_substrings) if question.expect_answerable else 0
    grounded = verification_status in ("supported", "partially_supported")
    correctly_declined = (not question.expect_answerable) and verification_status == "insufficient_evidence"

    return AIQuestionResult(
        question=question.question,
        hit=(rank > 0) if question.expect_answerable else correctly_declined,
        reciprocal_rank=(1.0 / rank if rank else 0.0),
        grounded=grounded, verification_status=verification_status, correctly_declined=correctly_declined,
        latency_ms=latency_ms, prompt_tokens=data["metadata"].get("prompt_tokens"),
        completion_tokens=data["metadata"].get("completion_tokens"), cited_files=cited_files,
    )


def run_eval(base_url: str, repository_id: str, fixture: list[AIEvalQuestion]) -> list[AIQuestionResult]:
    """Run every fixture question (cold) and print a scorecard.

    Args:
        base_url: The backend's base URL.
        repository_id: The (already fully indexed) repository to query.
        fixture: The evaluation questions.

    Returns:
        Per-question results.
    """
    results = []
    with httpx.Client(base_url=base_url, timeout=60.0) as client:
        for question in fixture:
            result = run_question(client, repository_id, question, force_refresh=True)
            results.append(result)
            status = "PASS" if result.hit else "FAIL"
            print(f"[{status}] {result.latency_ms:5.0f}ms  verification={result.verification_status:<22} {question.question}")
            print(f"       cited files: {result.cited_files}")

    grounded_count = sum(1 for r in results if r.grounded)
    recall_at_k = sum(1 for r in results if r.hit) / len(results) if results else 0.0
    mrr_values = [r.reciprocal_rank for r in results if r.reciprocal_rank > 0]
    mrr = statistics.mean(mrr_values) if mrr_values else 0.0
    latencies = [r.latency_ms for r in results]
    token_counts = [r.completion_tokens for r in results if r.completion_tokens is not None]

    print("\n=== SCORECARD ===")
    print(f"Recall@K (correct evidence/decline):  {recall_at_k:.3f}")
    print(f"MRR (answerable questions only):      {mrr:.3f}")
    print(f"Groundedness (supported+partial):     {grounded_count}/{len(results)}")
    print(f"Latency mean/median (cold):            {statistics.mean(latencies):.0f}ms / {statistics.median(latencies):.0f}ms")
    if token_counts:
        print(f"Completion tokens mean:                {statistics.mean(token_counts):.0f}")
    return results


def measure_cache_latency(base_url: str, repository_id: str, question: str) -> tuple[float, float]:
    """Measure cold vs. warm (cache-hit) latency for one query.

    Args:
        base_url: The backend's base URL.
        repository_id: The repository to query.
        question: The query to time.

    Returns:
        ``(cold_ms, warm_ms)``.
    """
    with httpx.Client(base_url=base_url, timeout=60.0) as client:
        cold_started = time.perf_counter()
        client.post(f"/api/v1/repositories/{repository_id}/ask", json={"query": question, "options": {"force_refresh": True}})
        cold_ms = (time.perf_counter() - cold_started) * 1000

        warm_started = time.perf_counter()
        client.post(f"/api/v1/repositories/{repository_id}/ask", json={"query": question})
        warm_ms = (time.perf_counter() - warm_started) * 1000
    return cold_ms, warm_ms


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repository-id", required=True, help="UUID of an already fully-indexed repository.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend base URL.")
    args = parser.parse_args()

    results = run_eval(args.base_url, args.repository_id, DEFAULT_FIXTURE)

    print("\n=== CACHE LATENCY ===")
    cold_ms, warm_ms = measure_cache_latency(args.base_url, args.repository_id, DEFAULT_FIXTURE[0].question)
    print(f"cold={cold_ms:.0f}ms  warm={warm_ms:.0f}ms  speedup={cold_ms / warm_ms if warm_ms else 0:.1f}x")

    sys.exit(0 if all(r.hit for r in results) else 1)


if __name__ == "__main__":
    main()
