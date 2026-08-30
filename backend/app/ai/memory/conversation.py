"""Persistent conversation history (CLAUDE.md §7) — write path only.

Write-only this sprint: each answered question is logged to the
already-existing ``conversations`` table (created in Sprint 0B, unused
until now) for future analytics/history. Feeding conversation history
back into reasoning as multi-turn context is explicitly out of scope
for Sprint 5 — nothing in the spec asks for session IDs, turn
ordering, or multi-turn context assembly, and adding them here would
be unrequested scope expansion.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation

logger = logging.getLogger("codesage.ai.memory.conversation")


async def save_conversation_turn(
    session: AsyncSession, *, repository_id: uuid.UUID, question: str, answer: str,
    intent: str, verification_status: str, total_latency_ms: int,
) -> Conversation:
    """Persist one question/answer turn.

    Best-effort from the caller's perspective: a failure here should
    never fail the overall ``/ask`` request (the answer has already
    been produced and verified) — see ``ai_service.py``'s call site,
    which wraps this in its own try/except.

    Args:
        session: The active database session.
        repository_id: The repository this turn was about.
        question: The user's raw query.
        answer: The final (possibly downgraded) answer text.
        intent: The classified intent, as its string value.
        verification_status: The verification gate's final status, as its string value.
        total_latency_ms: The full pipeline's total latency for this turn.

    Returns:
        The persisted conversation row.
    """
    conversation = Conversation(
        id=uuid.uuid4(), repository_id=repository_id, question=question, answer=answer,
        intent=intent, verification_status=verification_status, total_latency_ms=total_latency_ms,
    )
    session.add(conversation)
    await session.flush()
    return conversation
