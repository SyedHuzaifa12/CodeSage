"""Reports service — the DI entry point ``reports/api.py`` depends on.

Implements the exact cache-first, idempotent generation flow required
by spec §8/§12/§13 (see the spec's closing "IMP NOTE"): validate ->
compute repository version -> check Redis -> check Postgres's latest
``ready`` row -> full generation pipeline only as a last resort ->
persist a new append-only row -> write-through to Redis.

Mirrors ``AIOrchestratorService``/``RetrievalService`` exactly:
constructor takes ``session``+``settings``, business logic lives here,
not in ``api.py`` or the generators (CLAUDE.md §10/§11).
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.redis import get_redis_client
from app.ingestion import repository as ingestion_db
from app.knowledge import repository as knowledge_db
from app.models.report import Report
from app.repository import repository as repository_db
from app.repository.exceptions import RepositoryNotFoundError
from app.reports import repository as reports_db
from app.reports.cache import build_cache_key, get_cached_report, set_cached_report
from app.reports.exceptions import ReportRepositoryNotIndexedError
from app.reports.generators import GeneratedReport, RepositoryFacts
from app.reports.generators import architecture, dependency_risk, health, onboarding, overview
from app.reports.schemas import (
    EvidenceConfidence,
    EvidenceReference,
    ReportDiagram,
    ReportResponse,
    ReportSection,
)
from app.reports.synthesis import synthesize_report_narrative
from app.reports.utils import default_title, dedupe_latest_per_type, is_stale, render_content_text, validate_report_type
from app.retrieval.cache import get_corpus_version

logger = logging.getLogger("codesage.reports.service")

_GENERATORS: dict[str, Callable[[RepositoryFacts], GeneratedReport]] = {
    "summary": overview.generate,
    "architecture": architecture.generate,
    "dependency_risk": dependency_risk.generate,
    "health": health.generate,
    "onboarding": onboarding.generate,
}


class ReportService:
    """Generates, caches, and retrieves Repository Intelligence Reports for one repository."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        """Initialize the service.

        Args:
            session: The request-scoped database session.
            settings: Application settings (report/LLM/retrieval config live here).
        """
        self._session = session
        self._settings = settings

    async def generate_or_get(
        self, repository_id: uuid.UUID, report_type: str, *, force_regenerate: bool = False,
    ) -> ReportResponse:
        """Return a valid report for one repository/type, generating it only if necessary.

        Args:
            repository_id: The repository the report is about.
            report_type: A validated Sprint 6 report type.
            force_regenerate: Skip cache and the "reuse the last ready
                row" fast path, always running the full pipeline.

        Returns:
            A structured, frontend-ready report.

        Raises:
            RepositoryNotFoundError: If no repository has that id.
            ReportRepositoryNotIndexedError: If knowledge-indexing hasn't finished yet.
        """
        report_type = validate_report_type(report_type)
        repository = await repository_db.get_by_id(self._session, repository_id)
        if repository is None:
            raise RepositoryNotFoundError(f"Repository '{repository_id}' was not found.")

        knowledge_state = await knowledge_db.get_index_state(self._session, repository_id)
        if knowledge_state is None or knowledge_state.status != "ready":
            raise ReportRepositoryNotIndexedError(
                f"Repository '{repository_id}' has not finished knowledge-indexing yet — run indexing first."
            )

        cfg = self._settings.reports
        current_version = await get_corpus_version(self._session, repository_id)
        redis_client = get_redis_client() if cfg.cache_enabled else None
        cache_key = build_cache_key(
            repository_id=repository_id, report_type=report_type, repository_version=current_version,
            llm_settings=self._settings.llm,
        )

        if redis_client is not None and not force_regenerate:
            cached = await get_cached_report(redis_client, cache_key)
            if cached is not None:
                logger.info("Report cache hit for repository %s type=%s", repository_id, report_type)
                return cached

        if not force_regenerate:
            latest_ready = await reports_db.get_latest(self._session, repository_id, report_type, status="ready")
            if latest_ready is not None and not is_stale(latest_ready.repository_version, current_version):
                response = self._to_response(latest_ready, current_version)
                if redis_client is not None:
                    await set_cached_report(redis_client, cache_key, response, cfg.cache_ttl_seconds)
                return response

        response = await self._generate_new(repository_id, report_type, current_version)
        if redis_client is not None and response.status == "ready":
            await set_cached_report(redis_client, cache_key, response, cfg.cache_ttl_seconds)
        return response

    async def get_latest(self, repository_id: uuid.UUID, report_type: str) -> Optional[ReportResponse]:
        """Fetch the latest ``ready`` report for one repository/type, without generating one.

        Args:
            repository_id: The repository to look up.
            report_type: A validated Sprint 6 report type.

        Returns:
            The latest ready report, with ``stale`` computed against
            the repository's current version, or ``None`` if none exists.
        """
        report_type = validate_report_type(report_type)
        latest_ready = await reports_db.get_latest(self._session, repository_id, report_type, status="ready")
        if latest_ready is None:
            return None
        current_version = await get_corpus_version(self._session, repository_id)
        return self._to_response(latest_ready, current_version)

    async def list_reports(self, repository_id: uuid.UUID, *, latest_only: bool = True) -> list[ReportResponse]:
        """List a repository's reports.

        Args:
            repository_id: The repository to list reports for.
            latest_only: If ``True`` (the default), return one row per
                report type (the newest); if ``False``, return full history.

        Returns:
            Reports, newest first, as structured responses.
        """
        rows = await reports_db.list_for_repository(self._session, repository_id)
        if latest_only:
            rows = dedupe_latest_per_type(rows)
        current_version = await get_corpus_version(self._session, repository_id)
        return [self._to_response(row, current_version) for row in rows]

    async def _generate_new(self, repository_id: uuid.UUID, report_type: str, current_version: str) -> ReportResponse:
        """Run the full generation pipeline and persist a new append-only report row.

        Never raises on a generator/synthesis failure — persists a
        ``failed`` row and returns it, per spec §8 ("never crash the
        request... return the failure status/error in the response
        instead of a 500 where reasonable").
        """
        started = time.perf_counter()
        attempted_at = datetime.now(timezone.utc)

        try:
            facts = await self._collect_facts(repository_id)
            generated = _GENERATORS[report_type](facts)
        except Exception as exc:  # noqa: BLE001 -- any deterministic-collection/generator bug must degrade, not 500
            logger.exception("Report generation failed for repository %s type=%s", repository_id, report_type)
            failed_row = Report(
                repository_id=repository_id, report_type=report_type, content=f"Report generation failed: {exc}",
                status="failed", generated_at=attempted_at, repository_version=current_version,
                title=default_title(report_type), error_message=str(exc),
                generation_metadata={"generation_ms": int((time.perf_counter() - started) * 1000)},
            )
            failed_row = await reports_db.create(self._session, failed_row)
            return self._to_response(failed_row, current_version)

        sections = list(generated.sections)
        summary = generated.summary
        generation_metadata: dict = {"generation_ms": 0, "ai_used": False}

        if generated.ai_section_headings and self._settings.reports.ai_synthesis_enabled:
            synthesis_result = await synthesize_report_narrative(
                facts_context=generated.ai_facts_context, section_headings=generated.ai_section_headings,
                evidence_for_verification=generated.ai_evidence_for_verification, llm_settings=self._settings.llm,
            )
            if synthesis_result.ai_synthesis_failed:
                generation_metadata["ai_synthesis_failed"] = True
                if synthesis_result.failure_reason:
                    generation_metadata["ai_synthesis_failure_reason"] = synthesis_result.failure_reason
                logger.warning(
                    "AI synthesis failed for repository %s type=%s — serving deterministic-only report.",
                    repository_id, report_type,
                )
            else:
                generation_metadata["ai_used"] = True
                generation_metadata["ai_provider"] = synthesis_result.provider
                generation_metadata["ai_model"] = synthesis_result.model
                if synthesis_result.summary:
                    summary = synthesis_result.summary
                for heading in generated.ai_section_headings:
                    synthesized = synthesis_result.sections.get(heading)
                    if synthesized is None:
                        continue
                    content = synthesized.narrative
                    if synthesized.confidence == EvidenceConfidence.INSUFFICIENT_EVIDENCE:
                        content = (
                            "[AI interpretation could not be fully grounded in repository evidence — "
                            "treat as unverified.] " + content
                        )
                    sections.append(
                        ReportSection(
                            heading=heading, content=content, confidence=synthesized.confidence,
                            evidence=[], metrics={}, findings=[],
                        )
                    )
        elif generated.ai_section_headings:
            generation_metadata["ai_synthesis_skipped"] = "disabled_by_configuration"

        generation_metadata["generation_ms"] = int((time.perf_counter() - started) * 1000)

        title = generated.title
        content_text = render_content_text(title, summary, sections)
        flattened_evidence: list[EvidenceReference] = [item for section in sections for item in section.evidence]

        report_row = Report(
            repository_id=repository_id, report_type=report_type, content=content_text, status="ready",
            generated_at=attempted_at, repository_version=current_version, title=title, summary=summary,
            sections=[section.model_dump(mode="json") for section in sections],
            evidence=[item.model_dump(mode="json") for item in flattened_evidence],
            diagrams=[diagram.model_dump(mode="json") for diagram in generated.diagrams],
            generation_metadata=generation_metadata,
        )
        report_row = await reports_db.create(self._session, report_row)
        logger.info(
            "Generated report for repository %s type=%s status=ready generation_ms=%d ai_used=%s",
            repository_id, report_type, generation_metadata["generation_ms"], generation_metadata.get("ai_used"),
        )
        return self._to_response(report_row, current_version)

    async def _collect_facts(self, repository_id: uuid.UUID) -> RepositoryFacts:
        """Gather every piece of already-parsed/analyzed repository data a generator might need.

        Reuses Sprint 2A/2B's persisted data verbatim (spec §3) — never
        re-runs Tree-sitter parsing, never regenerates embeddings, never
        rebuilds intelligence.
        """
        repository = await repository_db.get_by_id(self._session, repository_id)
        intelligence = await ingestion_db.get_intelligence(self._session, repository_id)
        files = await ingestion_db.list_files(self._session, repository_id)
        symbols = await ingestion_db.list_symbols_for_repository(self._session, repository_id)
        relationships = await ingestion_db.list_relationships(self._session, repository_id)
        return RepositoryFacts(
            repository=repository, intelligence=intelligence, files=files, symbols=symbols, relationships=relationships,
        )

    def _to_response(self, report: Report, current_repository_version: str) -> ReportResponse:
        """Convert a persisted ``Report`` row into the API's structured response shape."""
        return ReportResponse(
            id=report.id, repository_id=report.repository_id, report_type=report.report_type, status=report.status,
            title=report.title, summary=report.summary,
            sections=[ReportSection.model_validate(item) for item in (report.sections or [])],
            diagrams=[ReportDiagram.model_validate(item) for item in (report.diagrams or [])],
            generation_metadata=report.generation_metadata or {}, repository_version=report.repository_version,
            generated_at=report.generated_at, created_at=report.created_at, error_message=report.error_message,
            stale=is_stale(report.repository_version, current_repository_version),
        )
