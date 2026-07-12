"""Shared, module-agnostic response envelope (CLAUDE.md §10).

Every successful API response wraps its payload in this shape:
``{"success": true, "message": "...", "data": {...}}``. Error responses
use the separate ``{success, message, errors}`` shape built by
``app.exceptions.handlers.build_error_response``.
"""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

DataT = TypeVar("DataT")


class SuccessResponse(BaseModel, Generic[DataT]):
    """Standard success envelope wrapping a typed ``data`` payload."""

    success: bool = True
    message: str
    data: DataT
