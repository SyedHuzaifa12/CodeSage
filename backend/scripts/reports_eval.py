"""CodeSage Reports Evaluation — Sprint 6.

Follows ``ai_eval.py``/``retrieval_eval.py``'s exact style (a small,
honest dataclass fixture against one real, already-indexed repository;
prints a scorecard; never fabricates numbers) applied to the Repository
Intelligence Reports API instead of ``/ask``.

Measures, per spec §21:

- **Factual/evidence accuracy** — whether each report type's evidence
  (flattened ``EvidenceReference.file_path`` values across sections)
  contains at least one of the expected real file paths for that
  report type on the target repository.
- **Unsupported-claim rate** — the fraction of returned sections whose
  ``confidence`` is ``partial`` or ``insufficient_evidence`` (i.e. not
  presented as a fully-grounded fact).
- **Generation latency** — cold (``force_regenerate``) vs. cache-hit
  (warm) latency for the same report.

This fixture is intentionally small and tied to one real repository
(``miguelgrinberg/microblog``, the project's established live-validation
target) — it exists to catch regressions, not to be maximized.

Usage (from the backend/ directory, against a running Docker stack with
the target repository already fully indexed):

    python scripts/reports_eval.py --repository-id <uuid>
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from dataclasses import dataclass, field

import httpx


@dataclass
class ReportEvalCase:
    """One evaluation case: a report type and the file path(s) expected to appear in its evidence."""

    report_type: str
    expected_path_substrings: list[str]
    expect_diagram: bool = False


DEFAULT_FIXTURE: list[ReportEvalCase] = [
    ReportEvalCase("summary", ["app/__init__.py", "config.py"]),
    ReportEvalCase("architecture", ["app/"], expect_diagram=True),
    ReportEvalCase("dependency_risk", []),
    ReportEvalCase("health", []),
    ReportEvalCase("onboarding", ["app/__init__.py"]),
]


@dataclass
class ReportEvalResult:
    report_type: str
    status: str
    evidence_hit: bool
    unsupported_section_ratio: float
    diagram_present: bool
    diagram_valid: bool
    latency_ms: float
    total_sections: int
    evidence_file_paths: list[str] = field(default_factory=list)


def _flattened_evidence_paths(report_data: dict) -> list[str]:
    paths: list[str] = []
    for section in report_data.get("sections", []):
        for evidence in section.get("evidence", []):
            if evidence.get("file_path"):
                paths.append(evidence["file_path"])
    return paths


def run_case(client: httpx.Client, repository_id: str, case: ReportEvalCase, force_regenerate: bool) -> ReportEvalResult:
    """Generate one report type and score it against the expected evidence fixture.

    Args:
        client: An open HTTP client against the backend.
        repository_id: The repository to report on.
        case: The evaluation case to run.
        force_regenerate: Whether to bypass caching for this call.

    Returns:
        The scored result.
    """
    started = time.perf_counter()
    response = client.post(
        f"/api/v1/repositories/{repository_id}/reports/{case.report_type}",
        json={"force_regenerate": force_regenerate},
    )
    latency_ms = (time.perf_counter() - started) * 1000
    response.raise_for_status()
    data = response.json()["data"]

    evidence_paths = _flattened_evidence_paths(data)
    evidence_hit = (
        any(any(substring in path for path in evidence_paths) for substring in case.expected_path_substrings)
        if case.expected_path_substrings else True
    )

    sections = data.get("sections", [])
    unsupported = sum(1 for s in sections if s.get("confidence") in ("partial", "insufficient_evidence"))
    unsupported_ratio = unsupported / len(sections) if sections else 0.0

    diagrams = data.get("diagrams", [])
    diagram_present = bool(diagrams)
    diagram_valid = all(d.get("mermaid_code", "").startswith(("flowchart", "graph")) for d in diagrams) if diagrams else not case.expect_diagram

    return ReportEvalResult(
        report_type=case.report_type, status=data.get("status", "unknown"), evidence_hit=evidence_hit,
        unsupported_section_ratio=unsupported_ratio, diagram_present=diagram_present, diagram_valid=diagram_valid,
        latency_ms=latency_ms, total_sections=len(sections), evidence_file_paths=evidence_paths,
    )


def run_eval(base_url: str, repository_id: str, fixture: list[ReportEvalCase]) -> list[ReportEvalResult]:
    """Run every fixture case (cold) and print a scorecard.

    Args:
        base_url: The backend's base URL.
        repository_id: The (already fully indexed) repository to report on.
        fixture: The evaluation cases.

    Returns:
        Per-case results.
    """
    results = []
    with httpx.Client(base_url=base_url, timeout=120.0) as client:
        for case in fixture:
            result = run_case(client, repository_id, case, force_regenerate=True)
            results.append(result)
            status = "PASS" if (result.status == "ready" and result.evidence_hit) else "FAIL"
            print(
                f"[{status}] {result.latency_ms:7.0f}ms  status={result.status:<8} "
                f"sections={result.total_sections:<3} unsupported_ratio={result.unsupported_section_ratio:.2f}  {case.report_type}"
            )
            if case.expect_diagram:
                print(f"       diagram_present={result.diagram_present} diagram_valid={result.diagram_valid}")

    evidence_accuracy = sum(1 for r in results if r.evidence_hit) / len(results) if results else 0.0
    unsupported_rate = statistics.mean([r.unsupported_section_ratio for r in results]) if results else 0.0
    ready_rate = sum(1 for r in results if r.status == "ready") / len(results) if results else 0.0
    latencies = [r.latency_ms for r in results]

    print("\n=== SCORECARD ===")
    print(f"Generation success rate (status=ready):  {ready_rate:.3f}")
    print(f"Evidence accuracy (expected path found):  {evidence_accuracy:.3f}")
    print(f"Mean unsupported-section ratio:           {unsupported_rate:.3f}")
    print(f"Latency mean/median (cold):                {statistics.mean(latencies):.0f}ms / {statistics.median(latencies):.0f}ms")
    return results


def measure_cache_latency(base_url: str, repository_id: str, report_type: str) -> tuple[float, float]:
    """Measure cold vs. warm (cache-hit) latency for one report type.

    Args:
        base_url: The backend's base URL.
        repository_id: The repository to report on.
        report_type: The report type to time.

    Returns:
        ``(cold_ms, warm_ms)``.
    """
    with httpx.Client(base_url=base_url, timeout=120.0) as client:
        cold_started = time.perf_counter()
        client.post(f"/api/v1/repositories/{repository_id}/reports/{report_type}", json={"force_regenerate": True})
        cold_ms = (time.perf_counter() - cold_started) * 1000

        warm_started = time.perf_counter()
        client.post(f"/api/v1/repositories/{repository_id}/reports/{report_type}", json={"force_regenerate": False})
        warm_ms = (time.perf_counter() - warm_started) * 1000
    return cold_ms, warm_ms


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repository-id", required=True, help="UUID of an already fully-indexed repository.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend base URL.")
    args = parser.parse_args()

    results = run_eval(args.base_url, args.repository_id, DEFAULT_FIXTURE)

    print("\n=== CACHE LATENCY ===")
    cold_ms, warm_ms = measure_cache_latency(args.base_url, args.repository_id, DEFAULT_FIXTURE[0].report_type)
    print(f"cold={cold_ms:.0f}ms  warm={warm_ms:.0f}ms  speedup={cold_ms / warm_ms if warm_ms else 0:.1f}x")

    sys.exit(0 if all(r.status == "ready" and r.evidence_hit for r in results) else 1)


if __name__ == "__main__":
    main()
