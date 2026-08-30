"""Hybrid retrieval orchestration — the Sprint 4 pipeline.

    query -> analyze -> [semantic || lexical] -> structural (1 hop)
          -> dedup -> fuse/rank -> evidence -> RetrievalQueryData

Semantic (Qdrant + embedding model) and lexical (PostgreSQL) run
concurrently via ``asyncio.gather`` since they touch disjoint
resources (Qdrant/embedding vs. the request's ``AsyncSession``).
Structural retrieval runs afterward, sequentially, on the same
session — both because SQLAlchemy's ``AsyncSession`` doesn't support
concurrent statements on one connection, and because it genuinely
depends on semantic/lexical's results as its expansion seeds.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import RetrievalSettings, Settings
from app.db.qdrant import get_qdrant_client
from app.db.redis import get_redis_client
from app.ingestion import repository as ingestion_db
from app.knowledge.embedding import get_embedding_provider
from app.models.repository import Repository
from app.repository import repository as repository_db
from app.repository.exceptions import RepositoryNotFoundError
from app.retrieval.cache import get_cached_result, get_corpus_version, set_cached_result
from app.retrieval.candidates import Candidate, deduplicate, fuse_and_rank, query_has_test_intent
from app.retrieval.exceptions import InvalidQueryError
from app.retrieval.lexical import get_lexical_candidates
from app.retrieval.reranking import get_rerank_provider, read_candidate_text
from app.retrieval.repository import get_symbols_by_ids
from app.retrieval.schemas import EvidenceResult, RetrievalQueryData, RetrievalStats, SourceScore
from app.retrieval.semantic import get_semantic_candidates
from app.retrieval.structural import get_structural_candidates
from app.retrieval.utils import QueryAnalysis, StageTimer, analyze_query, cache_key

logger = logging.getLogger("codesage.retrieval.service")

VALID_SOURCES = frozenset({"semantic", "lexical", "structural"})
ALL_SOURCES = ("semantic", "lexical", "structural")


class RetrievalService:
    """Runs the hybrid retrieval pipeline for a single query against one repository."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        """Initialize the service.

        Args:
            session: The request-scoped database session.
            settings: Application settings (retrieval weights/limits live here).
        """
        self._session = session
        self._settings = settings

    async def query(
        self, repository_id: uuid.UUID, query: str, top_k: Optional[int], sources: Optional[list[str]],
        rerank_override: Optional[bool] = None,
    ) -> RetrievalQueryData:
        """Run the full hybrid retrieval pipeline.

        Args:
            repository_id: The repository to search — every retrieval
                source is scoped to this id; no result from any other
                repository can ever appear.
            query: The user's free-text query.
            top_k: Requested result count (clamped to
                ``RetrievalSettings.max_top_k``); defaults to
                ``RetrievalSettings.default_top_k`` if omitted.
            sources: Which retrieval sources to run (subset of
                ``semantic``/``lexical``/``structural``); all three if omitted.
            rerank_override: If given, overrides
                ``RetrievalSettings.reranking_enabled`` for this call
                only — never mutates the shared settings singleton, so
                concurrent requests are unaffected by each other's
                override. ``None`` uses the configured default.

        Returns:
            Ranked, evidence-bearing results plus observability stats.

        Raises:
            RepositoryNotFoundError: If no repository has that id.
            InvalidQueryError: If ``sources`` names an unrecognized source.
        """
        cfg = self._settings.retrieval
        effective_top_k = min(top_k or cfg.default_top_k, cfg.max_top_k)
        effective_sources = tuple(sources) if sources else ALL_SOURCES
        effective_reranking = cfg.reranking_enabled if rerank_override is None else rerank_override
        unknown = set(effective_sources) - VALID_SOURCES
        if unknown:
            raise InvalidQueryError(f"Unknown retrieval source(s): {sorted(unknown)}. Valid: {sorted(VALID_SOURCES)}")

        repository = await repository_db.get_by_id(self._session, repository_id)
        if repository is None:
            raise RepositoryNotFoundError(f"Repository '{repository_id}' was not found.")

        timer = StageTimer()
        analysis = analyze_query(query, max_tokens=cfg.lexical_tokens_per_query)

        if not analysis.normalized:
            return self._empty_response(repository_id, query, effective_top_k, effective_sources, timer, cache_hit=False)

        corpus_version = await get_corpus_version(self._session, repository_id)
        redis_client = get_redis_client() if cfg.cache_enabled else None
        key = cache_key(
            repository_id=str(repository_id), normalized_query=analysis.normalized,
            top_k=effective_top_k, sources=effective_sources, corpus_version=corpus_version,
            reranking_enabled=effective_reranking,
        )

        if redis_client is not None:
            with timer.stage("cache_lookup"):
                cached = await get_cached_result(redis_client, key)
            if cached is not None:
                cached.stats.cache_hit = True
                cached.stats.total_latency_ms = sum(timer.as_dict().values())
                cached.stats.stage_latency_ms = timer.as_dict()
                return cached

        result = await self._compute(
            repository=repository, query=query, analysis=analysis,
            top_k=effective_top_k, sources=effective_sources, timer=timer, reranking_enabled=effective_reranking,
        )

        if redis_client is not None:
            await set_cached_result(redis_client, key, result, cfg.cache_ttl_seconds)

        return result

    async def _compute(
        self, *, repository: Repository, query: str, analysis: QueryAnalysis, top_k: int,
        sources: tuple[str, ...], timer: StageTimer, reranking_enabled: bool,
    ) -> RetrievalQueryData:
        """Run every requested retrieval source, fuse, rank, rerank, and shape the response."""
        cfg = self._settings.retrieval
        repository_id = repository.id
        sources_failed: list[str] = []
        test_intent = query_has_test_intent(analysis.normalized)

        intelligence = await ingestion_db.get_intelligence(self._session, repository_id)
        entry_point_paths = frozenset(intelligence.entry_points) if intelligence else frozenset()
        hotspot_paths = (
            frozenset(h["module_path"] for h in intelligence.dependency_hotspots) if intelligence else frozenset()
        )

        tasks: dict[str, "asyncio.Task[list[Candidate]]"] = {}
        if "semantic" in sources:
            tasks["semantic"] = asyncio.create_task(self._safe_semantic(repository_id, query, cfg))
        if "lexical" in sources:
            tasks["lexical"] = asyncio.create_task(self._safe_lexical(repository_id, analysis, cfg))

        semantic_candidates: list[Candidate] = []
        lexical_candidates: list[Candidate] = []
        if tasks:
            with timer.stage("retrieval_parallel"):
                gathered = await asyncio.gather(*tasks.values())
            for name, outcome in zip(tasks.keys(), gathered):
                if outcome is None:
                    sources_failed.append(name)
                elif name == "semantic":
                    semantic_candidates = outcome
                else:
                    lexical_candidates = outcome

        structural_candidates: list[Candidate] = []
        if "structural" in sources:
            with timer.stage("structural"):
                outcome = await self._safe_structural(repository_id, semantic_candidates + lexical_candidates, cfg)
            if outcome is None:
                sources_failed.append("structural")
            else:
                structural_candidates = outcome

        rerank_pool_size = max(top_k, cfg.reranking_candidate_pool) if reranking_enabled else top_k

        with timer.stage("fusion"):
            all_candidates = semantic_candidates + lexical_candidates + structural_candidates
            deduped = deduplicate(all_candidates)
            ranked = fuse_and_rank(
                deduped,
                weight_semantic=cfg.weight_semantic, weight_lexical=cfg.weight_lexical,
                weight_structural=cfg.weight_structural, entry_point_boost=cfg.entry_point_boost,
                hotspot_boost=cfg.dependency_hotspot_boost, entry_point_paths=entry_point_paths,
                hotspot_module_paths=hotspot_paths, top_k=rerank_pool_size,
                test_intent_boost=cfg.test_intent_boost, query_test_intent=test_intent,
            )

        with timer.stage("symbol_enrichment"):
            await self._enrich_missing_symbol_info(ranked)

        reranking_applied = False
        if reranking_enabled and ranked:
            with timer.stage("reranking"):
                try:
                    ranked = await self._rerank(query, repository, ranked, cfg.reranking_max_chars)
                    reranking_applied = True
                except Exception:
                    logger.exception("Reranking failed for repository %s; keeping fusion ranking", repository_id)
                    sources_failed.append("reranker")

        ranked = ranked[:top_k]

        results = [
            EvidenceResult(
                rank=index + 1, final_score=candidate.final_score, rerank_score=candidate.rerank_score,
                repository_id=candidate.repository_id,
                file_id=candidate.file_id, file_path=candidate.file_path, chunk_id=candidate.chunk_id,
                symbol_id=candidate.symbol_id, symbol_name=candidate.symbol_name,
                qualified_name=candidate.qualified_name, symbol_type=candidate.symbol_type,
                start_line=candidate.start_line, end_line=candidate.end_line, language=candidate.language,
                sources=sorted(candidate.source_scores.keys()),
                source_scores=[SourceScore(source=s, score=v) for s, v in sorted(candidate.source_scores.items())],
                reasons=candidate.reasons,
            )
            for index, candidate in enumerate(ranked)
        ]

        stats = RetrievalStats(
            candidates_semantic=len(semantic_candidates), candidates_lexical=len(lexical_candidates),
            candidates_structural=len(structural_candidates), candidates_after_dedup=len(deduped),
            stage_latency_ms=timer.as_dict(), total_latency_ms=sum(timer.as_dict().values()),
            cache_hit=False, sources_failed=sources_failed, reranking_applied=reranking_applied,
        )
        logger.info(
            "Retrieval for repository %s: query_len=%d sources=%s semantic=%d lexical=%d structural=%d "
            "after_dedup=%d results=%d failed=%s total_ms=%d",
            repository_id, len(query), sources, len(semantic_candidates), len(lexical_candidates),
            len(structural_candidates), len(deduped), len(results), sources_failed, stats.total_latency_ms,
        )
        return RetrievalQueryData(
            repository_id=repository_id, query=query, top_k=top_k, sources_requested=list(sources),
            results=results, stats=stats,
        )

    async def _safe_semantic(
        self, repository_id: uuid.UUID, query: str, cfg: RetrievalSettings
    ) -> Optional[list[Candidate]]:
        try:
            provider = get_embedding_provider()
            return await get_semantic_candidates(
                qdrant_client=get_qdrant_client(), provider=provider, repository_id=repository_id,
                query=query, limit=cfg.semantic_candidate_limit, min_score=cfg.semantic_min_score,
            )
        except Exception:
            logger.exception("Semantic retrieval failed for repository %s", repository_id)
            return None

    async def _safe_lexical(
        self, repository_id: uuid.UUID, analysis: QueryAnalysis, cfg: RetrievalSettings
    ) -> Optional[list[Candidate]]:
        try:
            return await get_lexical_candidates(
                session=self._session, repository_id=repository_id, analysis=analysis,
                limit=cfg.lexical_candidate_limit, min_similarity=cfg.lexical_min_similarity,
            )
        except Exception:
            logger.exception("Lexical retrieval failed for repository %s", repository_id)
            return None

    async def _safe_structural(
        self, repository_id: uuid.UUID, seed_candidates: list[Candidate], cfg: RetrievalSettings
    ) -> Optional[list[Candidate]]:
        try:
            return await get_structural_candidates(
                session=self._session, repository_id=repository_id, seed_candidates=seed_candidates,
                max_seeds=cfg.structural_max_seeds, max_related=cfg.structural_max_seeds * cfg.structural_max_related_per_seed,
            )
        except Exception:
            logger.exception("Structural retrieval failed for repository %s", repository_id)
            return None

    async def _rerank(
        self, query: str, repository: Repository, candidates: list[Candidate], max_chars: int
    ) -> list[Candidate]:
        """Re-score fusion's top candidate pool by actual cross-encoder text relevance.

        Candidates whose text can no longer be read from disk (file
        deleted/renamed/binary since indexing) keep their fusion-based
        position rather than being dropped — a partial rerank is far
        better than none, and a missing file is not this request's
        fault.

        Args:
            query: The user's raw query text.
            repository: The owning repository (for its local clone path).
            candidates: Fusion's ranked candidate pool (mutated in place
                with each candidate's ``rerank_score``).
            max_chars: Per-candidate text truncation cap — cross-encoder
                cost scales roughly quadratically with sequence length,
                so this bounds latency independent of how large the
                original chunk was (see ``RetrievalSettings.reranking_max_chars``).

        Returns:
            Candidates re-sorted: every successfully-scored candidate
            first (by rerank score, descending), then any unscored
            candidates in their original fusion order.
        """
        texts: list[str] = []
        rerankable: list[Candidate] = []
        for candidate in candidates:
            text = read_candidate_text(repository, candidate, max_chars=max_chars)
            if text:
                texts.append(text)
                rerankable.append(candidate)

        if not texts:
            return candidates

        provider = get_rerank_provider()
        # Offloaded to a worker thread for the same reason as the
        # embedding call in semantic.py — cross-encoder inference is
        # synchronous CPU-bound work; inline it would block the event
        # loop (and every other concurrent request) for the duration.
        scores = await asyncio.to_thread(provider.rerank, query, texts)
        for candidate, score in zip(rerankable, scores):
            candidate.rerank_score = score
            candidate.reasons.append(f"reranked (cross-encoder score {score:.2f})")

        return sorted(candidates, key=lambda c: (c.rerank_score is None, -(c.rerank_score or 0.0)))

    async def _enrich_missing_symbol_info(self, ranked: list[Candidate]) -> None:
        """Backfill symbol name/qualified name/type for candidates that only carry a symbol id.

        Semantic hits come from Qdrant's payload, which stores
        ``symbol_id`` but not the symbol's human-readable name (kept
        out of the vector payload deliberately — Sprint 3 didn't need
        it there). One batched query resolves every such gap across the
        final ranked set, bounded to at most ``top_k`` rows.

        Args:
            ranked: The final, already-ranked candidates (mutated in place).
        """
        missing_ids = [c.symbol_id for c in ranked if c.symbol_id is not None and c.symbol_name is None]
        if not missing_ids:
            return
        symbols_by_id = await get_symbols_by_ids(self._session, missing_ids)
        for candidate in ranked:
            symbol = symbols_by_id.get(candidate.symbol_id) if candidate.symbol_id else None
            if symbol is not None:
                candidate.symbol_name = symbol.name
                candidate.qualified_name = symbol.qualified_name
                candidate.symbol_type = symbol.symbol_type

    @staticmethod
    def _empty_response(
        repository_id: uuid.UUID, query: str, top_k: int, sources: tuple[str, ...], timer: StageTimer, cache_hit: bool,
    ) -> RetrievalQueryData:
        """Build the canonical empty response for a blank/whitespace-only query."""
        return RetrievalQueryData(
            repository_id=repository_id, query=query, top_k=top_k, sources_requested=list(sources), results=[],
            stats=RetrievalStats(
                candidates_semantic=0, candidates_lexical=0, candidates_structural=0, candidates_after_dedup=0,
                stage_latency_ms=timer.as_dict(), total_latency_ms=sum(timer.as_dict().values()),
                cache_hit=cache_hit, sources_failed=[],
            ),
        )
