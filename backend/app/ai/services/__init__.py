"""AI Engine service package — the DI entry point for ``ai/api.py``."""
from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.postgres import get_db
from app.ai.services.ai_service import AIOrchestratorService

__all__ = ["AIOrchestratorService", "get_ai_service"]


def get_ai_service(
    session: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> AIOrchestratorService:
    """Build a request-scoped :class:`AIOrchestratorService`.

    Args:
        session: Injected database session.
        settings: Injected application settings.

    Returns:
        A service instance bound to this request's session.
    """
    return AIOrchestratorService(session=session, settings=settings)
