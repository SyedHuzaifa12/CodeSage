"""Unit tests for symbol-aware and fallback chunking (Sprint 3, Knowledge module).

No database, no Qdrant, no embedding model — these exercise pure
in-memory logic in ``app.knowledge.chunking``.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from app.knowledge.chunking import MAX_CHUNK_CHARS, chunk_file
from app.knowledge.utils import sha256_text


@dataclass
class FakeSymbol:
    """A minimal stand-in for ``models.Symbol`` — only the fields chunking reads."""

    id: uuid.UUID
    start_line: int
    end_line: int
    parent_symbol_id: Optional[uuid.UUID] = None


def make_symbol(start_line: int, end_line: int, parent: Optional[uuid.UUID] = None) -> FakeSymbol:
    return FakeSymbol(id=uuid.uuid4(), start_line=start_line, end_line=end_line, parent_symbol_id=parent)


class TestSymbolAwareChunking:
    def test_one_chunk_per_top_level_symbol(self) -> None:
        source = "\n".join(f"line{i}" for i in range(1, 21))
        func_symbol = make_symbol(start_line=5, end_line=10)
        class_symbol = make_symbol(start_line=12, end_line=20)

        chunks = chunk_file(source, [func_symbol, class_symbol])

        symbol_chunks = [c for c in chunks if c.chunk_type == "symbol"]
        assert len(symbol_chunks) == 2
        assert symbol_chunks[0].start_line == 5 and symbol_chunks[0].end_line == 10
        assert symbol_chunks[1].start_line == 12 and symbol_chunks[1].end_line == 20
        assert symbol_chunks[0].symbol_id == str(func_symbol.id)

    def test_methods_are_not_separately_chunked(self) -> None:
        """A method (has a parent) must not produce its own chunk — it's already inside the class chunk."""
        source = "\n".join(f"line{i}" for i in range(1, 11))
        class_symbol = make_symbol(start_line=1, end_line=10)
        method_symbol = make_symbol(start_line=2, end_line=5, parent=class_symbol.id)

        chunks = chunk_file(source, [class_symbol, method_symbol])

        assert len(chunks) == 1
        assert chunks[0].symbol_id == str(class_symbol.id)

    def test_leading_content_before_first_symbol_becomes_a_fallback_chunk(self) -> None:
        source = "import os\nimport sys\n\ndef foo():\n    pass\n"
        foo_symbol = make_symbol(start_line=4, end_line=5)

        chunks = chunk_file(source, [foo_symbol])

        assert chunks[0].chunk_type == "fallback"
        assert "import os" in chunks[0].text
        assert chunks[1].chunk_type == "symbol"

    def test_no_leading_chunk_when_first_symbol_starts_at_line_one(self) -> None:
        source = "def foo():\n    pass\n"
        foo_symbol = make_symbol(start_line=1, end_line=2)

        chunks = chunk_file(source, [foo_symbol])

        assert len(chunks) == 1
        assert chunks[0].chunk_type == "symbol"

    def test_oversized_symbol_is_split_with_overlap(self) -> None:
        # Each line is long enough that ~50 lines comfortably exceeds MAX_CHUNK_CHARS.
        long_line = "x" * 200
        lines = [long_line] * 50
        source = "\n".join(lines)
        big_symbol = make_symbol(start_line=1, end_line=50)

        chunks = chunk_file(source, [big_symbol])

        assert len(chunks) > 1
        assert all(c.chunk_type == "symbol_split" for c in chunks)
        assert all(len(c.text) <= MAX_CHUNK_CHARS for c in chunks)
        # Full line-range coverage: first chunk starts at line 1, last ends at line 50.
        assert chunks[0].start_line == 1
        assert chunks[-1].end_line == 50
        # chunk_index is sequential and starts at 0.
        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))

    def test_empty_symbol_span_is_skipped(self) -> None:
        # Single-line file where that one line is both the "symbol" and
        # whitespace-only — no leading content, no symbol text either.
        source = "   "
        blank_symbol = make_symbol(start_line=1, end_line=1)

        chunks = chunk_file(source, [blank_symbol])

        assert chunks == []


class TestFallbackChunking:
    def test_file_with_no_symbols_uses_fixed_size_windows(self) -> None:
        source = "\n".join(f"line{i}" for i in range(1, 101))

        chunks = chunk_file(source, [])

        assert len(chunks) > 1
        assert all(c.chunk_type == "fallback" for c in chunks)
        # Windows overlap, so consecutive chunks' start/end lines advance monotonically.
        for previous, current in zip(chunks, chunks[1:]):
            assert current.start_line > previous.start_line

    def test_empty_file_produces_no_chunks(self) -> None:
        assert chunk_file("", []) == []

    def test_whitespace_only_file_produces_no_chunks(self) -> None:
        assert chunk_file("   \n\n   \n", []) == []


class TestContentHashing:
    def test_identical_text_hashes_identically(self) -> None:
        assert sha256_text("def foo(): pass") == sha256_text("def foo(): pass")

    def test_different_text_hashes_differently(self) -> None:
        assert sha256_text("def foo(): pass") != sha256_text("def bar(): pass")

    def test_draft_chunk_auto_computes_content_hash(self) -> None:
        source = "def foo():\n    return 1\n"
        symbol = make_symbol(start_line=1, end_line=2)
        chunks = chunk_file(source, [symbol])
        assert chunks[0].content_hash == sha256_text(chunks[0].text)
