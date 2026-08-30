"""CodeSage Retrieval Quality Evaluation — Sprint 4 + pre-Sprint-5 hardening pass.

A small, deterministic evaluation fixture: representative repository
questions with expected file path(s) that should appear in the top-K
hybrid retrieval results. Not a claim that retrieval is "good" just
because an endpoint returns data — this checks whether the *correct*
evidence actually surfaces, and reports the two standard IR metrics
that make that measurable:

- **Recall@K**: did any expected path appear anywhere in the top-K? (0 or 1 per question)
- **MRR** (Mean Reciprocal Rank): 1/rank of the first correct hit, 0 if none — rewards
  ranking a correct result *higher*, not just "somewhere in top-K".

Also reports cold vs. warm (cached) latency, and — via ``--rerank``
— an A/B comparison of cross-encoder reranking on vs. off, using the
same running server (no restart needed; see the retrieval API's
``rerank`` query-param override).

Intentionally lightweight (HTTP calls against a running backend, a
plain JSON fixture, a scorecard) so it's cheap to extend into the
project's formal retrieval benchmark later, without needing a test
framework or fixtures database of its own.

Usage (from the backend/ directory, against a running Docker stack
with the target repository already indexed):

    python scripts/retrieval_eval.py --repository-id <uuid>
    python scripts/retrieval_eval.py --repository-id <uuid> --rerank both   # A/B comparison

The default fixture below targets miguelgrinberg/microblog — a small,
real, well-known Flask app with genuine auth/db/test structure — used
for this sprint's live validation.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from dataclasses import dataclass

import httpx


@dataclass
class EvalQuestion:
    """One evaluation question: a query and the file path(s) that should show up in top-K."""

    question: str
    expected_path_substrings: list[str]
    top_k: int = 5
    sources: str | None = None


DEFAULT_FIXTURE: list[EvalQuestion] = [
    EvalQuestion("Where is authentication implemented?", ["app/auth/", "app/api/auth.py"]),
    EvalQuestion("Which files implement the User model?", ["app/models.py"]),
    EvalQuestion("What is related to User?", ["app/models.py"], sources="lexical,structural"),
    EvalQuestion("Where is the database connection configured?", ["config.py", "app/__init__.py"]),
    EvalQuestion("Which tests are related to authentication?", ["tests.py"]),
    EvalQuestion("Where should a change to the login form be made?", ["app/auth/forms.py", "app/auth/routes.py"]),
    EvalQuestion("Where is email sending implemented?", ["app/auth/email.py", "app/email.py"]),
    EvalQuestion("How are errors handled?", ["app/errors", "app/api/errors.py"]),
]


@dataclass
class QuestionResult:
    question: str
    hit: bool
    reciprocal_rank: float
    latency_ms: float
    paths: list[str]


def _first_hit_rank(paths: list[str], expected_substrings: list[str]) -> int:
    """Return the 1-indexed rank of the first path matching any expected substring, or 0."""
    for rank, path in enumerate(paths, start=1):
        if any(substring in path for substring in expected_substrings):
            return rank
    return 0


def run_question(
    client: httpx.Client, repository_id: str, question: EvalQuestion, rerank: bool | None
) -> QuestionResult:
    """Run one evaluation question and score it.

    Args:
        client: An open HTTP client against the backend.
        repository_id: The repository to query.
        question: The question to run.
        rerank: ``True``/``False`` to override reranking for this call, ``None`` for the server default.

    Returns:
        The scored result.
    """
    params: dict[str, object] = {"q": question.question, "top_k": question.top_k}
    if question.sources:
        params["sources"] = question.sources
    if rerank is not None:
        params["rerank"] = rerank

    started = time.perf_counter()
    response = client.get(f"/api/v1/repositories/{repository_id}/retrieval/query", params=params)
    latency_ms = (time.perf_counter() - started) * 1000
    response.raise_for_status()

    results = response.json()["data"]["results"]
    paths = [r["file_path"] for r in results]
    rank = _first_hit_rank(paths, question.expected_path_substrings)

    return QuestionResult(
        question=question.question, hit=rank > 0, reciprocal_rank=(1.0 / rank if rank else 0.0),
        latency_ms=latency_ms, paths=paths,
    )


def run_eval(
    base_url: str, repository_id: str, fixture: list[EvalQuestion], rerank: bool | None, label: str
) -> list[QuestionResult]:
    """Run every fixture question once and print a scorecard.

    Args:
        base_url: The backend's base URL.
        repository_id: The (already indexed) repository to query.
        fixture: The evaluation questions.
        rerank: ``True``/``False`` to override reranking, ``None`` for the server default.
        label: A short label for this run, printed in the header (e.g. "rerank=ON").

    Returns:
        Per-question results, for aggregate metrics / A-B comparison.
    """
    print(f"\n=== {label} ===")
    results = []
    with httpx.Client(base_url=base_url, timeout=60.0) as client:
        for question in fixture:
            result = run_question(client, repository_id, question, rerank)
            results.append(result)
            status = "PASS" if result.hit else "FAIL"
            print(f"[{status}] rank={_rank_label(result.reciprocal_rank)} {result.latency_ms:5.0f}ms  {question.question}")
            print(f"       expected one of: {question.expected_path_substrings}")
            print(f"       top-{question.top_k} paths: {result.paths}")

    recall_at_k = sum(1 for r in results if r.hit) / len(results) if results else 0.0
    mrr = statistics.mean(r.reciprocal_rank for r in results) if results else 0.0
    latencies = [r.latency_ms for r in results]
    print(
        f"\n{label}: Recall@K={recall_at_k:.3f}  MRR={mrr:.3f}  "
        f"latency_mean={statistics.mean(latencies):.0f}ms  latency_median={statistics.median(latencies):.0f}ms"
    )
    return results


def _rank_label(reciprocal_rank: float) -> str:
    return f"{round(1 / reciprocal_rank)}" if reciprocal_rank > 0 else "-"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repository-id", required=True, help="UUID of an already-indexed repository.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend base URL.")
    parser.add_argument(
        "--rerank", choices=["default", "on", "off", "both"], default="default",
        help="'default' uses the server's configured setting; 'on'/'off' override it; "
        "'both' runs the fixture twice for an A/B comparison.",
    )
    args = parser.parse_args()

    if args.rerank == "both":
        off_results = run_eval(args.base_url, args.repository_id, DEFAULT_FIXTURE, rerank=False, label="rerank=OFF")
        on_results = run_eval(args.base_url, args.repository_id, DEFAULT_FIXTURE, rerank=True, label="rerank=ON")
        off_recall = sum(1 for r in off_results if r.hit) / len(off_results)
        on_recall = sum(1 for r in on_results if r.hit) / len(on_results)
        off_mrr = statistics.mean(r.reciprocal_rank for r in off_results)
        on_mrr = statistics.mean(r.reciprocal_rank for r in on_results)
        print(f"\n=== A/B SUMMARY ===\nRecall@K: {off_recall:.3f} -> {on_recall:.3f}\nMRR:      {off_mrr:.3f} -> {on_mrr:.3f}")
        sys.exit(0 if on_recall >= off_recall else 1)

    rerank_value = {"on": True, "off": False, "default": None}[args.rerank]
    results = run_eval(args.base_url, args.repository_id, DEFAULT_FIXTURE, rerank=rerank_value, label=f"rerank={args.rerank}")
    sys.exit(0 if all(r.hit for r in results) else 1)


if __name__ == "__main__":
    main()
