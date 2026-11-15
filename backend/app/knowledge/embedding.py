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
from typing import Callable, Protocol

import httpx
import redis.asyncio as redis

from app.core.config import LLMSettings, get_settings
from app.knowledge.exceptions import (
    EmbeddingConfigurationError,
    EmbeddingQuotaExceededError,
    EmbeddingRequestError,
    EmbeddingUnavailableError,
)

logger = logging.getLogger("codesage.knowledge.embedding")

_CACHE_KEY_PREFIX = "codesage:embedding"


class EmbeddingProvider(Protocol):
    """Interface every embedding backend must implement."""

    dimension: int
    version: str
    batch_size: int  # most texts the caller should hand to one embed() call

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
        self.batch_size = settings.embedding_batch_size

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


_MAX_RETRY_AFTER_SECONDS = 20.0
_QUOTA_ERROR_CODES = {4006}  # Workers AI: "you have used up your daily free allocation" (from Cloudflare's docs, not reproducible without spending the quota)


def _read_cloudflare_error(response: httpx.Response) -> tuple[int | None, str]:
    """Extract ``(code, message)`` from a Cloudflare error body without ever raising."""
    try:
        errors = response.json().get("errors") or []
        first = errors[0] if errors else {}
        return first.get("code"), str(first.get("message", ""))[:200]
    except Exception:  # noqa: BLE001 -- an unparseable error body must not mask the HTTP status
        return None, response.text[:200]


class CloudflareEmbeddingProvider:
    """Hosted embeddings via Cloudflare Workers AI (ADR-029).

    Same BGE-small weights as ``FastEmbedProvider``, 384 dimensions, so
    vectors are interchangeable *when pooling matches*: this provider
    requests CLS pooling (Cloudflare's default is mean) and was measured
    at cosine 1.0000 against the local model. Exists so a 512MB host never
    loads the ~300MB ONNX model.

    Synchronous on purpose, to match ``EmbeddingProvider.embed`` — callers
    run it in a worker thread. Failures are raised as ``EmbeddingError``
    subclasses carrying user-safe messages; the API token is never put in
    a message or log line.
    """

    def __init__(
        self,
        settings: LLMSettings,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Validate configuration and open the HTTP client.

        Args:
            settings: The active LLM/embedding settings.
            client: Optional pre-built client (tests inject a mock transport).
            sleep: Delay function used between retries (tests inject a no-op).

        Raises:
            EmbeddingConfigurationError: If the account id or token is missing.
        """
        token = settings.cloudflare_api_token
        if not settings.cloudflare_account_id or token is None:
            raise EmbeddingConfigurationError(
                "Cloudflare embeddings are enabled but CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN are not set."
            )
        self.dimension = settings.embedding_dimension
        self.version = settings.embedding_version
        self.batch_size = max(1, settings.cloudflare_embedding_batch_size)
        self._pooling = settings.cloudflare_embedding_pooling
        self._max_retries = max(0, settings.cloudflare_max_retries)
        self._backoff = settings.cloudflare_retry_backoff_seconds
        self._sleep = sleep
        self._url = (
            f"https://api.cloudflare.com/client/v4/accounts/{settings.cloudflare_account_id}"
            f"/ai/run/{settings.cloudflare_embedding_model}"
        )
        self._client = client or httpx.Client(timeout=settings.cloudflare_timeout_seconds)
        self._headers = {"Authorization": f"Bearer {token.get_secret_value()}"}
        self.neurons_used = 0.0  # running total from Cloudflare's cf-ai-neurons header, for cost visibility

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts, splitting into API-sized requests.

        Args:
            texts: Chunk texts to embed, in order.

        Returns:
            One 384-dimensional vector per input, same order.

        Raises:
            EmbeddingQuotaExceededError: Daily free quota is used up.
            EmbeddingUnavailableError: Network failure or repeated 429/5xx.
            EmbeddingConfigurationError: Token rejected.
            EmbeddingRequestError: The input itself was rejected.
        """
        if not texts:  # Cloudflare answers an empty list with HTTP 400
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(self._embed_request(texts[start : start + self.batch_size]))
        return vectors

    def _embed_request(self, texts: list[str]) -> list[list[float]]:
        attempt = 0
        while True:
            attempt += 1
            retry_after: float | None = None
            try:
                response = self._client.post(
                    self._url, headers=self._headers, json={"text": texts, "pooling": self._pooling}
                )
            except httpx.HTTPError as exc:
                failure = f"network error ({type(exc).__name__})"
            else:
                if response.status_code == 200:
                    return self._parse(response, len(texts))
                code, message = _read_cloudflare_error(response)
                status = response.status_code
                if code in _QUOTA_ERROR_CODES or "daily free allocation" in message.lower():
                    raise EmbeddingQuotaExceededError(
                        "The hosted embedding service's daily free quota is used up. Indexing stopped; "
                        "files already indexed are kept. Try again after 00:00 UTC."
                    )
                if status in (401, 403):
                    raise EmbeddingConfigurationError(
                        f"Cloudflare rejected the embedding API token (HTTP {status}); check CLOUDFLARE_API_TOKEN."
                    )
                if status != 429 and status < 500:
                    raise EmbeddingRequestError(f"Cloudflare rejected the embedding request (HTTP {status}): {message}")
                failure = f"HTTP {status}"
                retry_after = _parse_retry_after(response)

            if attempt > self._max_retries:
                raise EmbeddingUnavailableError(
                    f"The hosted embedding service is unavailable ({failure}) after {attempt} attempts. "
                    "Indexing stopped; files already indexed are kept. Try again in a few minutes."
                )
            delay = retry_after if retry_after is not None else self._backoff * 2 ** (attempt - 1)
            logger.warning("Cloudflare embeddings %s; retry %d/%d in %.1fs", failure, attempt, self._max_retries, delay)
            self._sleep(delay)

    def _parse(self, response: httpx.Response, expected: int) -> list[list[float]]:
        try:
            body = response.json()
            result = body["result"]
            data = result["data"]
            returned_pooling = result.get("pooling")
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingUnavailableError("The hosted embedding service returned an unreadable response.") from exc
        # A silent fallback to mean pooling would corrupt retrieval without any error, so verify what was actually used.
        if returned_pooling is not None and returned_pooling != self._pooling:
            raise EmbeddingConfigurationError(
                f"Cloudflare used '{returned_pooling}' pooling but '{self._pooling}' was requested."
            )
        if len(data) != expected or any(len(vector) != self.dimension for vector in data):
            raise EmbeddingUnavailableError("The hosted embedding service returned vectors of an unexpected shape.")
        try:
            self.neurons_used += float(response.headers.get("cf-ai-neurons", 0))
        except ValueError:
            pass
        return [[float(x) for x in vector] for vector in data]


def _parse_retry_after(response: httpx.Response) -> float | None:
    """Return the server's ``Retry-After`` seconds, capped, or ``None`` if absent/unusable."""
    try:
        return min(max(float(response.headers["retry-after"]), 0.0), _MAX_RETRY_AFTER_SECONDS)
    except (KeyError, ValueError):
        return None


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
    if settings.embedding_provider == "cloudflare":
        return CloudflareEmbeddingProvider(settings)
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
