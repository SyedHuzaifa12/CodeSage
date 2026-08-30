"""AI Engine service — the DI entry point ``ai/api.py`` depends on.

Mirrors ``RetrievalService``/``KnowledgeService`` exactly: constructor
takes ``session``+``settings``, one public async method does the work.
Owns everything that wraps the pipeline itself (cache lookup/write,
repository validation, the hard total-timeout, conversation
persistence, exception mapping) — never the pipeline's internal logic,
which lives entirely in ``ai/engine/orchestrator.py``.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.cache import build_cache_key, get_ai_corpus_version, get_cached_answer, set_cached_answer
from app.ai.engine.orchestrator import run_pipeline
from app.ai.exceptions import AIError, LLMProviderError, LLMTimeoutError, RepositoryNotReadyForAIError
from app.ai.graph.state import AIGraphState
from app.ai.memory import save_conversation_turn
from app.ai.schemas.dto import AskResponseData
from app.core.config import Settings
from app.db.redis import get_redis_client
from app.knowledge import repository as knowledge_db
from app.repository import repository as repository_db
from app.repository.exceptions import RepositoryNotFoundError
from app.retrieval.utils import analyze_query

logger = logging.getLogger("codesage.ai.services.ai_service")


class AIOrchestratorService:
    """Runs the AI Engine pipeline for a single question against one repository."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        """Initialize the service.

        Args:
            session: The request-scoped database session.
            settings: Application settings (AI/LLM/retrieval config live here).
        """
        self._session = session
        self._settings = settings

    async def ask(
        self, repository_id: uuid.UUID, query: str, *, top_k: Optional[int] = None,
        sources: Optional[list[str]] = None, force_refresh: bool = False,
    ) -> AskResponseData:
        """Answer one repository question, grounded in retrieved evidence.

        Args:
            repository_id: The repository to answer about — every
                stage is scoped to this id; no cross-repository leakage
                is possible (validated up front, and baked into the
                cache key).
            query: The user's free-text question.
            top_k: Optional retrieval top-K override.
            sources: Optional retrieval sources override.
            force_refresh: Bypass the AI answer cache for this request.

        Returns:
            The grounded, cited, verified answer.

        Raises:
            RepositoryNotFoundError: If no repository has that id.
            RepositoryNotReadyForAIError: If the repository hasn't finished knowledge-indexing yet.
            LLMTimeoutError: If the whole pipeline exceeds its total timeout budget.
        """
        cfg = self._settings.ai
        request_id = str(uuid.uuid4())
        total_started = time.perf_counter()

        repository = await repository_db.get_by_id(self._session, repository_id)
        if repository is None:
            raise RepositoryNotFoundError(f"Repository '{repository_id}' was not found.")

        knowledge_state = await knowledge_db.get_index_state(self._session, repository_id)
        if knowledge_state is None or knowledge_state.status != "ready":
            raise RepositoryNotReadyForAIError(
                f"Repository '{repository_id}' has not finished knowledge-indexing yet — run indexing first."
            )

        analysis = analyze_query(query)
        redis_client = get_redis_client() if cfg.answer_cache_enabled else None
        cache_key: Optional[str] = None

        if redis_client is not None and analysis.normalized:
            # The key is computed (and, below, written to) regardless of
            # force_refresh — only the *lookup* is skipped for a forced
            # refresh. Gating key computation itself on force_refresh
            # would mean a forced-refresh call never populates the
            # cache, so every subsequent normal call would incorrectly
            # miss forever.
            corpus_version = await get_ai_corpus_version(self._session, repository_id)
            cache_key = build_cache_key(
                repository_id=repository_id, normalized_query=analysis.normalized, top_k=top_k, sources=sources,
                corpus_version=corpus_version, llm_settings=self._settings.llm,
            )
            if not force_refresh:
                cached = await get_cached_answer(redis_client, cache_key)
                if cached is not None:
                    cached.metadata.cache_hit = True
                    cached.metadata.stage_latency_ms.total_ms = int((time.perf_counter() - total_started) * 1000)
                    logger.info("AI cache hit for repository %s (request %s)", repository_id, request_id)
                    return cached

        initial_state: AIGraphState = {
            "request_id": request_id, "repository_id": repository_id, "repository": repository, "query": query,
            "top_k_override": top_k, "sources_override": sources, "session": self._session, "settings": self._settings,
            "retry_count": 0, "force_insufficient": False, "stage_latency_ms": {},
        }

        try:
            final_state = await asyncio.wait_for(run_pipeline(initial_state), timeout=cfg.total_timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise LLMTimeoutError(f"The AI pipeline exceeded its total timeout budget ({cfg.total_timeout_seconds}s).") from exc
        except (LLMProviderError, LLMTimeoutError):
            raise
        except Exception as exc:  # noqa: BLE001 -- any unexpected internal failure must not leak as a raw 500
            logger.exception("AI pipeline crashed for repository %s (request %s)", repository_id, request_id)
            raise AIError(f"The AI pipeline failed unexpectedly: {exc}") from exc

        response: AskResponseData = final_state["final_response"]
        logger.info(
            "AI answer for repository %s (request %s): intent=%s verification=%s retries=%d total_ms=%d",
            repository_id, request_id, response.metadata.intent, response.verification.status,
            response.metadata.retry_count, response.metadata.stage_latency_ms.total_ms,
        )

        if redis_client is not None and cache_key is not None:
            await set_cached_answer(redis_client, cache_key, response, cfg.answer_cache_ttl_seconds)

        try:
            await save_conversation_turn(
                self._session, repository_id=repository_id, question=query, answer=response.answer,
                intent=response.metadata.intent, verification_status=response.verification.status,
                total_latency_ms=response.metadata.stage_latency_ms.total_ms,
            )
        except Exception:  # noqa: BLE001 -- persisting history must never fail an already-produced answer
            logger.warning("Failed to persist conversation turn for repository %s (non-fatal)", repository_id, exc_info=True)

        return response
