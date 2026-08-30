"""Knowledge indexing background-task entry point.

Mirrors ``ingestion/parsing_service.run_parsing_pipeline``: a
``BackgroundTask`` never reuses the request-scoped session (already
closed by the time it actually runs), so this always opens its own
fresh session.
"""
from __future__ import annotations

import logging
import uuid

from app.db.postgres import get_session_factory
from app.knowledge.service import KnowledgeService

logger = logging.getLogger("codesage.knowledge.pipeline")


async def run_knowledge_indexing_pipeline(repository_id: uuid.UUID) -> None:
    """Background-task entry point: knowledge-index a repository using a fresh session.

    Args:
        repository_id: The repository to index.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            service = KnowledgeService(session)
            await service.index_repository(repository_id)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("Knowledge indexing pipeline crashed for repository %s", repository_id)
