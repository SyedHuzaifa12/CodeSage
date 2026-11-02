"""Unit tests for cross-file batching in ``KnowledgeService`` (pipeline-optimization pass).

Exercises ``KnowledgeService._index_file_batch`` directly with fake
Postgres/Redis/Qdrant collaborators (no real infrastructure) to verify
the two concrete, measurable claims this pass makes:

1. One embedding-model call processes a whole batch of changed files,
   not one call per file (``provider.embed`` call count == 1 for N
   changed files in one batch).
2. One Qdrant upsert call writes the whole batch's points, not one call
   per file.

Also covers the file-level incremental-indexing fast path still working
correctly when batching (an unchanged file contributes nothing to the
pooled embed/upsert calls) and per-file isolation of a read failure
without discarding the rest of the batch outcome's accounting.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pytest

from app.knowledge.service import KnowledgeService


@dataclass
class FakeFile:
    id: uuid.UUID
    path: str
    language: Optional[str] = "Python"


@dataclass
class FakeRepository:
    id: uuid.UUID
    local_path: str


class FakeProvider:
    """Counts calls and returns one fixed-length vector per input text."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeRedis:
    async def mget(self, keys: list[str]):
        return [None for _ in keys]

    def pipeline(self, transaction: bool = False):
        return self

    def set(self, *args, **kwargs):
        return self

    async def execute(self):
        return None


class FakeQdrantClient:
    def __init__(self) -> None:
        self.upsert_calls: list[list] = []
        self.delete_calls: list[list[str]] = []

    async def upsert(self, collection_name: str, points: list) -> None:
        self.upsert_calls.append(points)

    async def delete(self, collection_name: str, points_selector) -> None:
        self.delete_calls.append(points_selector)


class FakeSession:
    """Not touched directly by ``_index_file_batch`` — all DB access goes through ``knowledge_db``."""


@pytest.fixture()
def service(monkeypatch: pytest.MonkeyPatch) -> KnowledgeService:
    from app.knowledge import service as service_module

    async def _is_file_up_to_date(session, file_id, file_hash, embedding_version):
        return False  # every file in these tests is "changed"

    async def _get_chunk_ids_for_files(session, file_ids):
        return []

    async def _delete_chunks_for_files(session, file_ids):
        return None

    async def _insert_chunks(session, chunks):
        return None

    monkeypatch.setattr(service_module.knowledge_db, "is_file_up_to_date", _is_file_up_to_date)
    monkeypatch.setattr(service_module.knowledge_db, "get_chunk_ids_for_files", _get_chunk_ids_for_files)
    monkeypatch.setattr(service_module.knowledge_db, "delete_chunks_for_files", _delete_chunks_for_files)
    monkeypatch.setattr(service_module.knowledge_db, "insert_chunks", _insert_chunks)

    return KnowledgeService(session=FakeSession())


def _make_repo_with_files(tmp_path: Path, count: int) -> tuple[FakeRepository, list[FakeFile]]:
    repository = FakeRepository(id=uuid.uuid4(), local_path=str(tmp_path))
    files = []
    for i in range(count):
        rel_path = f"module_{i}.py"
        (tmp_path / rel_path).write_text(f"def fn_{i}():\n    return {i}\n", encoding="utf-8")
        files.append(FakeFile(id=uuid.uuid4(), path=rel_path))
    return repository, files


class TestCrossFileBatching:
    async def test_one_embed_call_and_one_upsert_call_per_batch(self, tmp_path: Path, service: KnowledgeService):
        repository, files = _make_repo_with_files(tmp_path, count=5)
        provider = FakeProvider()
        redis_client = FakeRedis()
        qdrant_client = FakeQdrantClient()

        result = await service._index_file_batch(
            repository=repository,
            batch=files,
            symbols_by_file={},
            embedding_version="fastembed:test:384",
            provider=provider,
            redis_client=redis_client,
            qdrant_client=qdrant_client,
            cache_ttl_seconds=60,
            provider_batch_size=32,
        )

        assert len(provider.calls) == 1, "expected exactly one pooled embed() call for the whole batch"
        assert len(qdrant_client.upsert_calls) == 1, "expected exactly one pooled upsert() call for the whole batch"
        assert result.files_failed == 0
        assert result.chunks_embedded_fresh > 0

    async def test_unchanged_file_contributes_nothing_to_the_batch(self, tmp_path: Path, monkeypatch, service):
        from app.knowledge import service as service_module

        repository, files = _make_repo_with_files(tmp_path, count=3)

        changed_ids = {files[0].id, files[1].id}

        async def _is_file_up_to_date(session, file_id, file_hash, embedding_version):
            return file_id not in changed_ids  # files[2] is "already up to date"

        monkeypatch.setattr(service_module.knowledge_db, "is_file_up_to_date", _is_file_up_to_date)

        provider = FakeProvider()
        result = await service._index_file_batch(
            repository=repository,
            batch=files,
            symbols_by_file={},
            embedding_version="fastembed:test:384",
            provider=provider,
            redis_client=FakeRedis(),
            qdrant_client=FakeQdrantClient(),
            cache_ttl_seconds=60,
            provider_batch_size=32,
        )

        assert result.files_skipped == 1
        # Only the two changed files' chunks reach the single pooled embed call.
        assert len(provider.calls) == 1
        embedded_texts = provider.calls[0]
        assert any("fn_0" in t for t in embedded_texts)
        assert any("fn_1" in t for t in embedded_texts)
        assert not any("fn_2" in t for t in embedded_texts)

    async def test_embed_calls_are_sub_batched_to_a_bounded_size(self, tmp_path: Path, service: KnowledgeService):
        """Regression test for a real failure found via live validation.

        Pooling an entire file-batch's misses into one ``provider.embed()``
        call (no cap) reproduced the exact OOM failure class the 512KB
        per-file size cap was built to prevent, but via aggregate chunk
        count instead of a single oversized file (observed live on
        ``sujeet-agrahari/nodejs-microservices-example``: a 25-file batch's
        pooled embed call crashed ONNX with a 336MB allocation failure).
        The fix sub-batches ``misses`` to ``provider_batch_size`` per
        ``embed()`` call — this test locks that behavior in.
        """
        repository, files = _make_repo_with_files(tmp_path, count=20)
        provider = FakeProvider()

        await service._index_file_batch(
            repository=repository,
            batch=files,
            symbols_by_file={},
            embedding_version="fastembed:test:384",
            provider=provider,
            redis_client=FakeRedis(),
            qdrant_client=FakeQdrantClient(),
            cache_ttl_seconds=60,
            provider_batch_size=4,
        )

        assert len(provider.calls) > 1, "expected multiple sub-batched embed() calls, not one unbounded call"
        assert all(len(call) <= 4 for call in provider.calls)

    async def test_unreadable_file_is_isolated_within_the_batch(self, tmp_path: Path, service: KnowledgeService):
        repository, files = _make_repo_with_files(tmp_path, count=3)
        missing = FakeFile(id=uuid.uuid4(), path="does_not_exist.py")
        batch = files + [missing]

        result = await service._index_file_batch(
            repository=repository,
            batch=batch,
            symbols_by_file={},
            embedding_version="fastembed:test:384",
            provider=FakeProvider(),
            redis_client=FakeRedis(),
            qdrant_client=FakeQdrantClient(),
            cache_ttl_seconds=60,
            provider_batch_size=32,
        )

        assert result.files_failed == 1
        assert result.chunks_embedded_fresh > 0  # the 3 readable files still indexed successfully
