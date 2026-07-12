"""Shared exception hierarchy for infrastructure-level failures.

Business-specific exceptions (``RepositoryNotFound``, ``IndexingFailed``,
etc., per CLAUDE.md §14) live inside the module that owns them. This
module only covers cross-cutting infrastructure failures — the kind
raised during application startup, before any business module runs.
"""
from __future__ import annotations


class CodeSageError(Exception):
    """Base class for all CodeSage application errors."""


class DatabaseConnectionError(CodeSageError):
    """Raised when PostgreSQL cannot be reached."""


class CacheConnectionError(CodeSageError):
    """Raised when Redis cannot be reached."""


class VectorStoreConnectionError(CodeSageError):
    """Raised when Qdrant cannot be reached."""
