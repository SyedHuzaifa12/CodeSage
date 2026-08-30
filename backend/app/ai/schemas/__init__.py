"""AI Engine contracts — intent classification, verification, and API DTOs."""
from __future__ import annotations

from app.ai.schemas.dto import (
    AskMetadata,
    AskOptions,
    AskRequest,
    AskResponseData,
    Citation,
    StageLatency,
    VerificationInfo,
)
from app.ai.schemas.intent import IntentAnalysis, QueryIntent
from app.ai.schemas.verification import CitationCheck, VerificationResult, VerificationStatus

__all__ = [
    "AskMetadata",
    "AskOptions",
    "AskRequest",
    "AskResponseData",
    "Citation",
    "StageLatency",
    "VerificationInfo",
    "IntentAnalysis",
    "QueryIntent",
    "CitationCheck",
    "VerificationResult",
    "VerificationStatus",
]
