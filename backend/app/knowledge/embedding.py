"""Embedding provider abstraction + Redis-backed embedding cache.

The provider is deliberately decoupled from the caller: ``knowledge/
service.py`` only ever calls ``EmbeddingProvider.embed(texts)`` and
reads ``.dimension``/``.version`` — swapping to a hosted embedding API
later means adding one more class here, never touching the service.

Model loading is process-wide and lazy (first actual embed call), since
constructing the model reads weights from disk — too slow to redo per
request or per background job.
"""
from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Protocol

import redis.asyncio as redis

from app.core.config import LLMSettings, get_settings

logger = logging.getLogger("codesage.knowledge.embedding")

_CACHE_KEY_PREFIX = "codesage:embedding"


class EmbeddingProvider(Protocol):
    """Interface every embedding backend must implement."""

    dimension: int
    version: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts.

        Args:
            texts: Chunk texts to embed, in order.

        Returns:
            One vector per input text, same order, each of length ``dimension``.
        """
        ...


class FastEmbedProvider:
    """Local, offline embedding provider backed by ``fastembed`` (ONNX Runtime).

    Chosen over ``sentence-transformers``/PyTorch and over a hosted
    embedding API: no external network dependency or API cost, no GPU
    framework tax on a CPU-only deployment, and a small on-disk
    footprint (~70MB for the default model vs. several hundred MB to
    over a GB once PyTorch is in the dependency tree) — all first-class
    concerns per this sprint's latency and footprint requirements. Runs
    the same ``BAAI/bge-small-en-v1.5`` weights sentence-transformers
    would have used, ONNX-exported, so retrieval quality is unaffected
    by this library choice.
    """

    def __init__(self, settings: LLMSettings) -> None:
        """Load the configured model.

        Args:
            settings: The active LLM/embedding settings.
        """
        # Imported lazily so a process that never indexes anything (e.g.
        # a short-lived script) never pays fastembed's import cost, and
        # so the dependency is easy to swap later.
        from fastembed import TextEmbedding

        self.dimension = settings.embedding_dimension
        self.version = settings.embedding_version
        self._model_name = settings.embedding_model
        self._batch_size = settings.embedding_batch_size

        load_started = time.perf_counter()
        self._model = TextEmbedding(model_name=settings.embedding_model, cache_dir=settings.embedding_model_cache_dir)
        logger.info(
            "Loaded embedding model '%s' (dimension=%d) in %dms",
            settings.embedding_model, self.dimension, int((time.perf_counter() - load_started) * 1000),
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts with the loaded model.

        Args:
            texts: Chunk texts to embed, in order.

        Returns:
            One vector per input text, same order.
        """
        if not texts:
            return []
        vectors = self._model.embed(texts, batch_size=self._batch_size)
        return [vector.tolist() for vector in vectors]


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    """Return the process-wide cached embedding provider.

    Reads settings internally (rather than taking them as a parameter)
    because ``LLMSettings`` is a mutable Pydantic model and therefore
    not hashable — this mirrors ``get_qdrant_client()``/
    ``get_redis_client()``'s no-argument, settings-read-inside pattern.
    The model is loaded exactly once per process, on first use.

    Returns:
        A ready-to-use embedding provider.

    Raises:
        ValueError: If an unrecognized provider is configured.
    """
    settings = get_settings().llm
    if settings.embedding_provider == "fastembed":
        return FastEmbedProvider(settings)
    raise ValueError(f"Unknown embedding provider: {settings.embedding_provider!r}")


def _cache_key(version: str, content_hash: str) -> str:
    """Build the Redis key for one (embedding-version, chunk-hash) pair."""
    return f"{_CACHE_KEY_PREFIX}:{version}:{content_hash}"


async def get_cached_embeddings(
    client: redis.Redis, version: str, content_hashes: list[str]
) -> dict[str, list[float]]:
    """Batch-fetch cached vectors for a set of chunk-content hashes.

    A cache miss (key absent, or Redis unreachable) is never an error —
    Redis is a pure performance cache here (CLAUDE.md §9: never a
    durable store), so any miss just means the embedding gets
    recomputed from the model instead.

    Args:
        client: The shared Redis client.
        version: The active embedding version (``LLMSettings.embedding_version``).
        content_hashes: Chunk content hashes to look up.

    Returns:
        Mapping of content_hash to vector, containing only cache hits.
    """
    if not content_hashes:
        return {}
    try:
        keys = [_cache_key(version, h) for h in content_hashes]
        raw_values = await client.mget(keys)
    except Exception:
        logger.warning("Redis embedding-cache lookup failed; falling back to full recompute", exc_info=True)
        return {}

    hits: dict[str, list[float]] = {}
    for content_hash, raw in zip(content_hashes, raw_values):
        if raw is None:
            continue
        try:
            hits[content_hash] = [float(v) for v in raw.split(",")]
        except ValueError:
            continue
    return hits


async def set_cached_embeddings(
    client: redis.Redis, version: str, vectors_by_hash: dict[str, list[float]], ttl_seconds: int
) -> None:
    """Batch-write freshly computed vectors into the Redis cache.

    Best-effort: a write failure is logged and swallowed rather than
    failing the indexing job — the vector is already safely persisted
    in Qdrant/Postgres regardless of whether the cache write succeeds.

    Args:
        client: The shared Redis client.
        version: The active embedding version.
        vectors_by_hash: Freshly computed vectors, keyed by content hash.
        ttl_seconds: Cache entry lifetime.
    """
    if not vectors_by_hash:
        return
    try:
        pipeline = client.pipeline(transaction=False)
        for content_hash, vector in vectors_by_hash.items():
            pipeline.set(_cache_key(version, content_hash), ",".join(str(v) for v in vector), ex=ttl_seconds)
        await pipeline.execute()
    except Exception:
        logger.warning("Redis embedding-cache write failed (non-fatal)", exc_info=True)
