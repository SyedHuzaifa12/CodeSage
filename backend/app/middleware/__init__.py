"""Middleware registration for the FastAPI application."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core.config import Settings
from app.middleware.request_id import RequestIDMiddleware


def register_middleware(app: FastAPI, settings: Settings) -> None:
    """Register all application middleware in the correct execution order.

    Starlette applies the LAST-registered middleware as the OUTERMOST
    layer, so ``RequestIDMiddleware`` is added last: it must see every
    request first (to bind the correlation ID before anything else runs)
    and every response last (to guarantee the response header survives).

    Args:
        app: The FastAPI application instance to register middleware on.
        settings: Application settings, used for CORS and trusted-host config.
    """
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.app.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.app.allowed_hosts_list)
    app.add_middleware(RequestIDMiddleware)
