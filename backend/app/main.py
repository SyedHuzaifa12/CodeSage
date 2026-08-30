"""CodeSage FastAPI application entry point.

Wires configuration, logging, lifespan, middleware, exception handlers,
and routers together.
"""
from __future__ import annotations

from fastapi import FastAPI

from app.ai.api import router as ai_router
from app.ai.exceptions import register_ai_exception_handlers
from app.api.health import router as health_router
from app.api.logs import router as logs_router
from app.core.config import get_settings
from app.core.lifespan import lifespan
from app.core.logging import configure_logging
from app.exceptions.handlers import register_exception_handlers
from app.ingestion.api import router as ingestion_router
from app.ingestion.exceptions import register_ingestion_exception_handlers
from app.knowledge.api import router as knowledge_router
from app.knowledge.exceptions import register_knowledge_exception_handlers
from app.middleware import register_middleware
from app.repository.api import router as repository_router
from app.repository.exceptions import register_repository_exception_handlers
from app.reports.api import router as reports_router
from app.reports.exceptions import register_reports_exception_handlers
from app.retrieval.api import router as retrieval_router
from app.retrieval.exceptions import register_retrieval_exception_handlers

configure_logging()
settings = get_settings()

app = FastAPI(
    title=settings.app.app_name,
    version=settings.app.app_version,
    debug=settings.app.debug,
    lifespan=lifespan,
)

register_middleware(app, settings)
register_exception_handlers(app)
register_repository_exception_handlers(app)
register_ingestion_exception_handlers(app)
register_knowledge_exception_handlers(app)
register_retrieval_exception_handlers(app)
register_ai_exception_handlers(app)
register_reports_exception_handlers(app)

app.include_router(health_router)
app.include_router(repository_router, prefix=settings.app.api_v1_prefix)
app.include_router(ingestion_router, prefix=settings.app.api_v1_prefix)
app.include_router(knowledge_router, prefix=settings.app.api_v1_prefix)
app.include_router(retrieval_router, prefix=settings.app.api_v1_prefix)
app.include_router(ai_router, prefix=settings.app.api_v1_prefix)
app.include_router(reports_router, prefix=settings.app.api_v1_prefix)
app.include_router(logs_router, prefix=settings.app.api_v1_prefix)
