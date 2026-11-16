"""Holds this process's indexing runner, if it has one.

Kept in its own tiny module so API-side code (which only needs to know "is a
runner living in this process?") can import it without pulling in the runner
and the whole indexing pipeline behind it.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.indexing.runner import IndexingRunner

_runner: Optional["IndexingRunner"] = None


def get_runner() -> Optional["IndexingRunner"]:
    """The runner living in this process, if any (``None`` in an API-only process)."""
    return _runner


def set_runner(runner: Optional["IndexingRunner"]) -> None:
    """Register (or clear) this process's runner."""
    global _runner
    _runner = runner
