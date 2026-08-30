"""Chunking strategies — symbol-aware first, fixed-size fallback second.

Reuses Sprint 2A's already-persisted ``Symbol`` rows (name, type,
start/end line) instead of re-parsing or re-deriving structure. Two
chunking strategies:

- **Symbol-aware** (``chunk_type="symbol"``/``"symbol_split"``): one
  chunk per *top-level* symbol (``parent_symbol_id is None``) — a
  top-level class's span already includes its own methods, so methods
  are not separately chunked (avoids duplicate embedding work for the
  same lines). A symbol whose span is too large for one embedding
  input is split into fixed-size, slightly overlapping sub-chunks
  (``symbol_split``).
- **Fallback** (``chunk_type="fallback"``): fixed-size line windows,
  used for any file with zero top-level symbols — unparsed languages
  (Markdown, YAML, JSON, CSS, ...) and Tree-sitter-parsed files that
  happen to have no top-level symbol (e.g. import-only files).

Files with no recognized language are never chunked at all (checked by
the caller in ``knowledge/service.py``) — there is nothing meaningful
to embed for a binary or unrecognized-extension file.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.knowledge.utils import DraftChunk

if TYPE_CHECKING:
    from app.models.symbol import Symbol

# Kept small enough to comfortably fit common embedding-model context
# windows (bge-small: 512 tokens) without a tokenizer dependency —
# character count is a cheap, good-enough proxy for token count here.
MAX_CHUNK_CHARS = 3_500
SPLIT_OVERLAP_LINES = 3

FALLBACK_WINDOW_LINES = 40
FALLBACK_OVERLAP_LINES = 5


def chunk_file(source_text: str, symbols: list["Symbol"]) -> list[DraftChunk]:
    """Chunk one file's source text, symbol-aware where possible.

    Args:
        source_text: The file's decoded UTF-8 source.
        symbols: Every ``Symbol`` row already parsed for this file
            (Sprint 2A) — only top-level symbols (no parent) are used
            as chunk boundaries.

    Returns:
        Ordered draft chunks, each with a sequential ``chunk_index``.
    """
    lines = source_text.splitlines()
    if not lines:
        return []

    top_level = sorted(
        (s for s in symbols if s.parent_symbol_id is None), key=lambda s: s.start_line
    )
    if not top_level:
        return _chunk_fallback(lines)
    return _chunk_by_symbols(lines, top_level)


def _chunk_by_symbols(lines: list[str], top_level: list["Symbol"]) -> list[DraftChunk]:
    """Build one chunk per top-level symbol, splitting oversized ones.

    Args:
        lines: The file's source, split into lines.
        top_level: Top-level symbols, already sorted by ``start_line``.

    Returns:
        Ordered draft chunks.
    """
    chunks: list[DraftChunk] = []
    index = 0

    first_start = top_level[0].start_line
    leading = "\n".join(lines[: first_start - 1]).strip()
    if leading:
        chunks.append(
            DraftChunk(text=leading, chunk_index=index, chunk_type="fallback", start_line=1, end_line=first_start - 1)
        )
        index += 1

    for symbol in top_level:
        start, end = symbol.start_line, symbol.end_line
        text = "\n".join(lines[start - 1 : end])
        if not text.strip():
            continue
        if len(text) <= MAX_CHUNK_CHARS:
            chunks.append(
                DraftChunk(
                    text=text, chunk_index=index, chunk_type="symbol",
                    start_line=start, end_line=end, symbol_id=str(symbol.id),
                )
            )
            index += 1
            continue

        for sub_start, sub_end, sub_text in _split_oversized(lines, start, end):
            chunks.append(
                DraftChunk(
                    text=sub_text, chunk_index=index, chunk_type="symbol_split",
                    start_line=sub_start, end_line=sub_end, symbol_id=str(symbol.id),
                )
            )
            index += 1

    return chunks


def _split_oversized(lines: list[str], start: int, end: int) -> list[tuple[int, int, str]]:
    """Split one symbol's line range into overlapping, size-bounded windows.

    Args:
        lines: The file's source, split into lines.
        start: The symbol's 1-indexed start line (inclusive).
        end: The symbol's 1-indexed end line (inclusive).

    Returns:
        ``(window_start_line, window_end_line, window_text)`` tuples.
    """
    windows: list[tuple[int, int, str]] = []
    cursor = start
    while cursor <= end:
        window_end = cursor
        text = lines[cursor - 1]
        next_line = cursor + 1
        while next_line <= end and len(text) + len(lines[next_line - 1]) + 1 <= MAX_CHUNK_CHARS:
            text += "\n" + lines[next_line - 1]
            window_end = next_line
            next_line += 1
        windows.append((cursor, window_end, text))
        if window_end >= end:
            break
        cursor = max(window_end - SPLIT_OVERLAP_LINES + 1, cursor + 1)
    return windows


def _chunk_fallback(lines: list[str]) -> list[DraftChunk]:
    """Fixed-size, overlapping line-window chunking for files with no symbols.

    Args:
        lines: The file's source, split into lines.

    Returns:
        Ordered draft chunks.
    """
    chunks: list[DraftChunk] = []
    index = 0
    cursor = 1
    total = len(lines)

    while cursor <= total:
        window_end = min(cursor + FALLBACK_WINDOW_LINES - 1, total)
        text = "\n".join(lines[cursor - 1 : window_end]).strip()
        if text:
            chunks.append(
                DraftChunk(text=text, chunk_index=index, chunk_type="fallback", start_line=cursor, end_line=window_end)
            )
            index += 1
        if window_end >= total:
            break
        cursor = max(window_end - FALLBACK_OVERLAP_LINES + 1, cursor + 1)

    return chunks
