"""Health, liveness, and readiness endpoints.

Deliberately unversioned (mounted outside ``/api/v1``): infrastructure
probes (Docker HEALTHCHECK, load balancers, container orchestrators)
need a stable path that does not shift with API versioning. See the
Sprint 0A architecture notes in ``backend/README.md`` for the rationale.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.core.config import Settings, get_settings
from app.db.postgres import check_postgres_connection
from app.db.qdrant import check_qdrant_connection
from app.db.redis import check_redis_connection

router = APIRouter(prefix="/health", tags=["health"])

_started_at = time.monotonic()


async def _dependency_statuses() -> dict[str, bool]:
    """Check every downstream dependency concurrently-safe in sequence.

    Returns:
        A mapping of dependency name to a boolean reachability flag.
    """
    return {
        "postgresql": await check_postgres_connection(),
        "redis": await check_redis_connection(),
        "qdrant": await check_qdrant_connection(),
    }


@router.get("")
async def health(settings: Settings = Depends(get_settings)) -> JSONResponse:
    """Report complete application status.

    Args:
        settings: Injected application settings.

    Returns:
        Application metadata, uptime, and per-dependency health, wrapped
        in the standard response envelope.
    """
    dependencies = await _dependency_statuses()
    healthy = all(dependencies.values())
    payload = {
        "success": healthy,
        "message": "CodeSage backend status.",
        "data": {
            "app_name": settings.app.app_name,
            "version": settings.app.app_version,
            "environment": settings.app.environment,
            "uptime_seconds": round(time.monotonic() - _started_at, 2),
            "dependencies": dependencies,
        },
    }
    status_code = status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=status_code, content=payload)


@router.get("/live")
async def liveness() -> JSONResponse:
    """Report process liveness.

    Intentionally performs no downstream checks — a liveness probe should
    only confirm the process itself is responsive, not restart it because
    a dependency is briefly degraded (that is what readiness is for).

    Returns:
        A 200 response confirming the process is alive.
    """
    payload = {"success": True, "message": "Application process is alive.", "data": {"alive": True}}
    return JSONResponse(status_code=status.HTTP_200_OK, content=payload)


@router.get("/ready")
async def readiness() -> JSONResponse:
    """Report readiness to serve traffic.

    Returns:
        200 with per-dependency status if PostgreSQL, Redis, and Qdrant
        are all reachable; 503 otherwise.
    """
    dependencies = await _dependency_statuses()
    ready = all(dependencies.values())
    payload = {
        "success": ready,
        "message": "Ready to serve traffic." if ready else "One or more dependencies are unavailable.",
        "data": {"ready": ready, "dependencies": dependencies},
    }
    status_code = status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=status_code, content=payload)
