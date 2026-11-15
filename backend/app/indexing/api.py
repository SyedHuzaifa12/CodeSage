"""Internal endpoints the API role uses to drive the indexer role (ADR-028).

Not for browsers: every route requires the shared ``X-Internal-Token`` secret.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.dependencies import require_internal_token
from app.indexing.registry import get_runner
from app.schemas.envelope import SuccessResponse

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(require_internal_token)])


def _runner_status() -> dict:
    runner = get_runner()
    if runner is None:
        return {"runner": False}
    runner.wake()
    return {"runner": True, **runner.status()}


@router.post("/wake", response_model=SuccessResponse[dict])
async def wake() -> SuccessResponse[dict]:
    """Ask the indexer to look for queued work now. Idempotent; wakes coalesce."""
    return SuccessResponse(message="Indexer woken.", data=_runner_status())


@router.post("/heartbeat", response_model=SuccessResponse[dict])
async def heartbeat() -> SuccessResponse[dict]:
    """Keep-alive while a job runs (the inbound request is what stops a free host spinning down).

    Also acts as a wake, which recovers a wake that was lost while the host was booting.
    """
    return SuccessResponse(message="Indexer alive.", data=_runner_status())
