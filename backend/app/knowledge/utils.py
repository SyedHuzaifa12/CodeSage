"""Shared hashing helpers and chunk data shape for the Knowledge module."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional


def sha256_text(text: str) -> str:
    """Hash a chunk's text content.

    Used as the chunk-level identity for incremental re-indexing and as
    the Redis embedding-cache key component — two chunks with identical
    text (even across different files/repositories, e.g. shared
    boilerplate or license headers) always hash identically and reuse
    one cached embedding.

    Args:
        text: The chunk's raw text.

    Returns:
        A hex-encoded SHA-256 digest.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class DraftChunk:
    """A chunk produced by chunking, before it has an embedding or a DB row."""

    text: str
    chunk_index: int
    chunk_type: str
    start_line: int
    end_line: int
    symbol_id: Optional[str] = None
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.content_hash:
            self.content_hash = sha256_text(self.text)
