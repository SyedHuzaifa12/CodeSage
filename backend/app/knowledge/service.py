"""Knowledge indexing pipeline — chunk, embed, and persist a repository's source.

Per CLAUDE.md §6, this stays inside the Knowledge module, which is the
only module allowed to write to Qdrant (ADR-provided boundary already
established for the Repository/Ingestion split). Chained directly
after Sprint 2B's ``RepositoryIntelligenceService.analyze_repository``
in the same background-task session (see
``parsing_service.run_parsing_pipeline``) — sequential, not a new
concurrent task, so it carries no new deadlock risk.

Latency-critical design choices:
- File-level fast path: a file whose own content hash and the active
  embedding version both already match its existing chunks is skipped
  entirely — no disk read for chunking, no model call, no Qdrant call.
- Chunk-level cache: within a changed file, only chunks whose *own*
  text hash isn't already cached in Redis reach the embedding model;
  identical code (duplicated across files/repos, e.g. license headers)
  reuses one cached vector.
- Batched embedding: all of one file's cache-misses are embedded in a
  single model call, not one call per chunk.
- Failure isolation: one file's read/decode/embedding failure is
  logged and skipped; it never aborts the rest of the repository.
"""
from __future__ import annotations

import hashlib
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.qdrant import get_qdrant_client
from app.db.redis import get_redis_client
from app.ingestion import repository as ingestion_db
from app.knowledge import qdrant_store
from app.knowledge import repository as knowledge_db
from app.knowledge.chunking import chunk_file
from app.knowledge.embedding import get_cached_embeddings, get_embedding_provider, set_cached_embeddings
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_index_state import KnowledgeIndexState
from app.repository import repository as repository_db

logger = logging.getLogger("codesage.knowledge.service")


class KnowledgeService:
    """Chunks, embeds, and persists a repository's indexable source files."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the service.

        Args:
            session: The database session this indexing run uses
                exclusively (shared with the parsing/intelligence steps
                that precede it — see module docstring).
        """
        self._session = session

    async def index_repository(self, repository_id: uuid.UUID) -> KnowledgeIndexState:
        """Run the full knowledge-indexing pipeline for a repository.

        Args:
            repository_id: The repository to index; must already be
                parsed (Sprint 2A) — symbols are read as-is, never
                re-derived here.

        Returns:
            The persisted (or updated) knowledge-index-state row.
        """
        state = await knowledge_db.get_index_state(self._session, repository_id)
        if state is None:
            state = await knowledge_db.create_index_state(
                self._session, KnowledgeIndexState(repository_id=repository_id, status="pending")
            )
        state.status = "indexing"
        state.progress = 0
        state.error_message = None
        await knowledge_db.save_index_state(self._session, state)
        logger.info("Knowledge index %s transitioning to INDEXING for repository %s", state.id, repository_id)

        total_started = time.perf_counter()
        chunking_ms = 0
        embedding_ms = 0
        upsert_ms = 0
        files_considered = 0
        files_skipped = 0
        files_failed = 0
        chunks_from_cache = 0
        chunks_embedded_fresh = 0

        try:
            repository = await repository_db.get_by_id(self._session, repository_id)
            if repository is None:
                raise ValueError(f"Repository '{repository_id}' was not found.")

            files = await ingestion_db.list_files(self._session, repository_id)
            symbols = await ingestion_db.list_symbols_for_repository(self._session, repository_id)
            symbols_by_file: dict[uuid.UUID, list] = {}
            for symbol in symbols:
                symbols_by_file.setdefault(symbol.file_id, []).append(symbol)

            settings = get_settings()
            embedding_version = settings.llm.embedding_version
            provider = get_embedding_provider()
            redis_client = get_redis_client()
            qdrant_client = get_qdrant_client()

            total_files = len(files)
            for index, file_row in enumerate(files, start=1):
                if not file_row.language:
                    continue
                files_considered += 1

                try:
                    result = await self._index_file(
                        repository=repository,
                        file_row=file_row,
                        file_symbols=symbols_by_file.get(file_row.id, []),
                        embedding_version=embedding_version,
                        provider=provider,
                        redis_client=redis_client,
                        qdrant_client=qdrant_client,
                        cache_ttl_seconds=settings.llm.embedding_cache_ttl_seconds,
                    )
                except (OSError, UnicodeDecodeError) as exc:
                    files_failed += 1
                    logger.warning("Skipping knowledge indexing for '%s': %s", file_row.path, exc)
                except Exception:  # noqa: BLE001 -- isolate this file, keep indexing the rest
                    files_failed += 1
                    logger.exception(
                        "Knowledge indexing failed for file '%s' in repository %s", file_row.path, repository_id
                    )
                else:
                    if result is None:
                        files_skipped += 1
                    else:
                        chunking_ms += result.chunking_ms
                        embedding_ms += result.embedding_ms
                        upsert_ms += result.upsert_ms
                        chunks_from_cache += result.chunks_from_cache
                        chunks_embedded_fresh += result.chunks_embedded_fresh

                state.progress = int(index / total_files * 100) if total_files else 100
                await knowledge_db.save_index_state(self._session, state)

            state.status = "ready"
            state.progress = 100
            state.embedding_model_version = embedding_version
            state.total_files_considered = files_considered
            state.total_files_skipped_unchanged = files_skipped
            state.total_files_failed = files_failed
            state.total_chunks = await knowledge_db.count_chunks(self._session, repository_id)
            state.total_chunks_from_cache = chunks_from_cache
            state.total_chunks_embedded_fresh = chunks_embedded_fresh
            state.last_indexed_at = datetime.now(timezone.utc)
            state.chunking_ms = chunking_ms
            state.embedding_ms = embedding_ms
            state.upsert_ms = upsert_ms
            state.total_ms = int((time.perf_counter() - total_started) * 1000)
            await knowledge_db.save_index_state(self._session, state)

            logger.info(
                "Knowledge index %s transitioned to READY for repository %s: "
                "files_considered=%d skipped_unchanged=%d failed=%d total_chunks=%d "
                "from_cache=%d embedded_fresh=%d chunking_ms=%d embedding_ms=%d upsert_ms=%d total_ms=%d",
                state.id, repository_id, files_considered, files_skipped, files_failed, state.total_chunks,
                chunks_from_cache, chunks_embedded_fresh, chunking_ms, embedding_ms, upsert_ms, state.total_ms,
            )
        except Exception as exc:  # noqa: BLE001 -- record failure, never crash the calling background task
            state.status = "failed"
            state.error_message = str(exc)
            await knowledge_db.save_index_state(self._session, state)
            logger.exception("Knowledge indexing failed for repository %s", repository_id)

        return state

    async def _index_file(
        self, *, repository, file_row, file_symbols, embedding_version, provider, redis_client, qdrant_client,
        cache_ttl_seconds: int,
    ) -> "_FileIndexResult | None":
        """Index one file: fast-path skip, chunk, embed (cache-aware), persist.

        Returns:
            ``None`` if the file was skipped via the fast path (content
            and embedding version unchanged); otherwise per-stage
            timings and cache-hit/miss counts for this file.
        """
        absolute_path = Path(repository.local_path) / file_row.path
        source_bytes = absolute_path.read_bytes()
        file_hash = hashlib.sha256(source_bytes).hexdigest()

        if await knowledge_db.is_file_up_to_date(self._session, file_row.id, file_hash, embedding_version):
            return None

        source_text = source_bytes.decode("utf-8")

        chunk_started = time.perf_counter()
        draft_chunks = chunk_file(source_text, file_symbols)
        chunking_ms = int((time.perf_counter() - chunk_started) * 1000)

        old_ids = await knowledge_db.get_chunk_ids_for_file(self._session, file_row.id)
        if old_ids:
            await knowledge_db.delete_chunks_for_file(self._session, file_row.id)
            await qdrant_store.delete_points_by_ids(qdrant_client, old_ids)

        if not draft_chunks:
            return _FileIndexResult(chunking_ms=chunking_ms, embedding_ms=0, upsert_ms=0, chunks_from_cache=0, chunks_embedded_fresh=0)

        hashes = [draft.content_hash for draft in draft_chunks]
        cached = await get_cached_embeddings(redis_client, embedding_version, hashes)
        misses = [draft for draft in draft_chunks if draft.content_hash not in cached]

        embed_started = time.perf_counter()
        fresh_vectors = provider.embed([draft.text for draft in misses]) if misses else []
        embedding_ms = int((time.perf_counter() - embed_started) * 1000)

        fresh_by_hash: dict[str, list[float]] = {}
        for draft, vector in zip(misses, fresh_vectors):
            fresh_by_hash.setdefault(draft.content_hash, vector)
        if fresh_by_hash:
            await set_cached_embeddings(redis_client, embedding_version, fresh_by_hash, cache_ttl_seconds)

        rows: list[KnowledgeChunk] = []
        points = []
        for draft in draft_chunks:
            vector = cached.get(draft.content_hash) or fresh_by_hash.get(draft.content_hash)
            if vector is None:
                continue  # only reachable if the embedding call itself silently dropped an input
            chunk_id = uuid.uuid4()
            symbol_uuid = uuid.UUID(draft.symbol_id) if draft.symbol_id else None
            rows.append(
                KnowledgeChunk(
                    id=chunk_id, repository_id=repository.id, file_id=file_row.id, symbol_id=symbol_uuid,
                    chunk_index=draft.chunk_index, chunk_type=draft.chunk_type,
                    start_line=draft.start_line, end_line=draft.end_line, char_count=len(draft.text),
                    language=file_row.language, content_hash=draft.content_hash,
                    file_content_hash=file_hash, embedding_model_version=embedding_version,
                )
            )
            points.append(
                qdrant_store.build_point(
                    chunk_id, vector, repository_id=repository.id, file_id=file_row.id, symbol_id=symbol_uuid,
                    file_path=file_row.path, language=file_row.language, chunk_type=draft.chunk_type,
                    start_line=draft.start_line, end_line=draft.end_line,
                    content_hash=draft.content_hash, embedding_model_version=embedding_version,
                )
            )

        upsert_started = time.perf_counter()
        await qdrant_store.upsert_points(qdrant_client, points)
        upsert_ms = int((time.perf_counter() - upsert_started) * 1000)

        await knowledge_db.insert_chunks(self._session, rows)

        return _FileIndexResult(
            chunking_ms=chunking_ms, embedding_ms=embedding_ms, upsert_ms=upsert_ms,
            chunks_from_cache=len(draft_chunks) - len(misses), chunks_embedded_fresh=len(misses),
        )


class _FileIndexResult:
    """Per-file timing and cache-hit/miss counters, aggregated by the caller."""

    __slots__ = ("chunking_ms", "embedding_ms", "upsert_ms", "chunks_from_cache", "chunks_embedded_fresh")

    def __init__(
        self, *, chunking_ms: int, embedding_ms: int, upsert_ms: int, chunks_from_cache: int, chunks_embedded_fresh: int
    ) -> None:
        self.chunking_ms = chunking_ms
        self.embedding_ms = embedding_ms
        self.upsert_ms = upsert_ms
        self.chunks_from_cache = chunks_from_cache
        self.chunks_embedded_fresh = chunks_embedded_fresh
