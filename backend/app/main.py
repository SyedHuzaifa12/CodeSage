"""CodeSage FastAPI application entry point.

Wires configuration, logging, lifespan, middleware, exception handlers,
and routers together. No business routes are registered here — Sprint 0A
establishes infrastructure only.
"""
from __future__ import annotations

from fastapi import FastAPI

from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.lifespan import lifespan
from app.core.logging import configure_logging
from app.exceptions.handlers import register_exception_handlers
from app.middleware import register_middleware

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
app.include_router(health_router)
