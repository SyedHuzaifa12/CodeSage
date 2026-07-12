"""Backend log-tail endpoint.

Exposes the most recent lines of the backend's own rotating log file so
the Streamlit DevTools console can display recent activity without ever
reading backend files directly — the same principle already applied to
Postgres/Redis/Qdrant access. Read-only; accepts no log input.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

from app.core.config import get_settings
from app.schemas.envelope import SuccessResponse

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("", response_model=SuccessResponse[dict])
async def get_recent_logs(limit: int = Query(200, ge=1, le=1000)) -> SuccessResponse[dict]:
    """Return the most recent backend log lines, newest first.

    Args:
        limit: Maximum number of lines to return.

    Returns:
        Parsed JSON log entries (or ``{"raw": line}`` for any line that
        isn't valid JSON), most recent first.
    """
    settings = get_settings()
    log_path = Path(settings.logging.log_dir) / settings.logging.log_file_name

    if not log_path.exists():
        return SuccessResponse(message="No log file found yet.", data={"lines": [], "total": 0})

    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()

    entries: list[Any] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            entries.append({"raw": line})

    entries.reverse()
    return SuccessResponse(message="Recent logs retrieved.", data={"lines": entries, "total": len(entries)})
