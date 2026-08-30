"""AI Engine REST API — routes only, no business logic (CLAUDE.md §10).

One endpoint, matching the exact conceptual shape in the Sprint 5 spec:
``POST /repositories/{id}/ask``. No second API architecture — same
router/envelope conventions as every other module.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.ai.schemas.dto import AskRequest, AskResponseData
from app.ai.services import AIOrchestratorService, get_ai_service
from app.schemas.envelope import SuccessResponse

router = APIRouter(prefix="/repositories/{repository_id}", tags=["ai"])


@router.post("/ask", response_model=SuccessResponse[AskResponseData])
async def ask_repository(
    repository_id: uuid.UUID, payload: AskRequest, service: AIOrchestratorService = Depends(get_ai_service),
) -> SuccessResponse[AskResponseData]:
    """Answer a question about a repository, grounded in retrieved evidence.

    Runs the full pipeline: intent analysis -> hybrid retrieval
    (Sprint 4, unmodified) -> evidence selection -> context
    construction -> LLM reasoning -> deterministic verification ->
    answer formatting. Every claim in the answer is checked against
    the actual retrieved evidence before being returned — see
    ``response.data.verification``.

    Args:
        repository_id: The repository to answer about.
        payload: The question and optional per-request overrides.
        service: Injected AI orchestrator service.

    Returns:
        The grounded, cited, verified answer.
    """
    options = payload.options
    data = await service.ask(
        repository_id, payload.query,
        top_k=options.top_k if options else None,
        sources=options.sources if options else None,
        force_refresh=options.force_refresh if options else False,
    )
    return SuccessResponse(message="Answer generated.", data=data)
