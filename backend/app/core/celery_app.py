"""Celery application bootstrap (ADR-026).

Lives in ``core/`` — not a business module — per CLAUDE.md §6's "System/
core: config, logging, auth, caching, health checks. Nothing
business-specific." This file only builds and configures the Celery
``app`` instance; it never defines task bodies itself (those live next
to the business logic they wrap — see ``app.ingestion.tasks``), mirroring
how ``db/postgres.py``/``db/redis.py``/``db/qdrant.py`` only provide
connections, never domain logic.

Reuses the existing Redis instance as both broker and result backend
(ADR-006's "no unnecessary infrastructure" principle — Celery is the
one new *framework* ADR-026 approves, not a new *datastore*), but on its
own logical Redis DB index, never the cache's (see ``CelerySettings``'s
docstring for why).
"""
from __future__ import annotations

import logging

from celery import Celery, signals

from app.core.config import get_settings

logger = logging.getLogger("codesage.core.celery_app")


def _build_redis_url(db: int) -> str:
    """Build a ``redis://`` URL for the given logical DB index.

    Args:
        db: The Redis logical database index to select.

    Returns:
        A connection URL usable as both a Celery broker and result backend.
    """
    settings = get_settings().redis
    auth = f":{settings.redis_password.get_secret_value()}@" if settings.redis_password else ""
    return f"redis://{auth}{settings.redis_host}:{settings.redis_port}/{db}"


def create_celery_app() -> Celery:
    """Construct the process-wide Celery application.

    Returns:
        A configured ``Celery`` instance. Task modules are imported via
        ``include`` so ``celery -A app.core.celery_app:celery_app worker``
        discovers them without a separate autodiscovery step.
    """
    celery_settings = get_settings().celery
    broker_url = _build_redis_url(celery_settings.celery_redis_db)

    app = Celery(
        "codesage",
        broker=broker_url,
        backend=broker_url,
        include=["app.ingestion.tasks"],
    )
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        result_expires=celery_settings.celery_task_time_limit_seconds * 2,
        task_acks_late=True,  # redeliver to another worker if this one dies mid-task
        worker_prefetch_multiplier=1,  # one indexing job at a time per worker slot — these are heavy, long tasks
        task_reject_on_worker_lost=True,
        task_time_limit=celery_settings.celery_task_time_limit_seconds,
        task_soft_time_limit=celery_settings.celery_task_soft_time_limit_seconds,
        task_default_queue="indexing",
        task_routes={"app.ingestion.tasks.*": {"queue": "indexing"}},
        timezone="UTC",
        enable_utc=True,
    )
    return app


celery_app = create_celery_app()


@signals.worker_ready.connect
@signals.worker_process_init.connect
def _warm_up_embedding_model(**kwargs) -> None:
    """Load the FastEmbed/ONNX model (and run one throwaway inference) at worker startup.

    Real, measured problem this fixes: ``get_embedding_provider()`` is
    process-wide ``@lru_cache``'d (correct — load the model once per
    process, not once per file/run), but each Celery worker is its own
    OS process, so each one independently pays the *first-ever-embed*
    cost. Loading the model alone is ~3-6s; observed live, the first
    real inference call on top of that paid a further, much larger,
    one-time ONNX session/thread-pool warm-up tax (125s on one worker
    process during this pass's own concurrency benchmark) — a user's
    first real indexing request landing on a freshly started worker
    would otherwise eat that cost, not just the model-load time. Running
    one dummy ``embed(["warmup"])`` call during worker startup moves
    that cost to worker readiness instead of a user-visible request.
    Connected to *both* ``worker_ready`` (fires once for the main
    process — the only one that matters for ``solo``/``threads``, which
    never spawn separate child processes) and ``worker_process_init``
    (fires once per forked child under ``prefork``, the pool Docker's
    container actually uses) so every pool type this project runs under
    gets pre-warmed exactly once; ``get_embedding_provider()``'s own
    ``@lru_cache`` makes a second call here a safe no-op if both ever
    fire in the same process.

    Best-effort: a failure here is logged, never fatal — the model will
    still load lazily (with the same warm-up cost) on the worker's first
    real task if this pre-warm itself fails for any reason.
    """
    try:
        from app.knowledge.embedding import get_embedding_provider

        provider = get_embedding_provider()
        provider.embed(["warmup"])
        logger.info("Embedding model pre-warmed for this worker process")
    except Exception:
        logger.warning("Embedding model pre-warm failed (non-fatal, will load lazily instead)", exc_info=True)
