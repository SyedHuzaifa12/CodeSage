"""File-system scanning and tree-building helpers.

Metadata only — no file is ever opened or its contents read. Tree-sitter
parsing and symbol extraction are explicitly out of scope for this
sprint (Sprint 2).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.ingestion.schemas import TreeNode
from app.models.file import File

IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
        "env", "dist", "build", "vendor", ".idea", ".vscode", ".mypy_cache",
        ".pytest_cache", ".ruff_cache", "target", ".next", ".turbo", "coverage",
    }
)

EXTENSION_LANGUAGE_MAP: dict[str, str] = {
    ".py": "Python", ".pyi": "Python",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin", ".kts": "Kotlin",
    ".rb": "Ruby",
    ".php": "PHP",
    ".c": "C", ".h": "C",
    ".cpp": "C++", ".cc": "C++", ".cxx": "C++", ".hpp": "C++",
    ".cs": "C#",
    ".swift": "Swift",
    ".m": "Objective-C",
    ".scala": "Scala",
    ".sh": "Shell", ".bash": "Shell",
    ".sql": "SQL",
    ".html": "HTML", ".htm": "HTML",
    ".css": "CSS", ".scss": "SCSS", ".less": "Less",
    ".json": "JSON",
    ".yaml": "YAML", ".yml": "YAML",
    ".toml": "TOML",
    ".md": "Markdown", ".mdx": "Markdown",
    ".xml": "XML",
    ".vue": "Vue",
    ".dart": "Dart",
    ".lua": "Lua",
    ".r": "R",
    ".pl": "Perl",
    ".ex": "Elixir", ".exs": "Elixir",
    ".hs": "Haskell",
    ".proto": "Protocol Buffers",
}


def detect_language(filename: str, extension: str) -> Optional[str]:
    """Guess a file's language from its name/extension alone.

    Args:
        filename: The file's base name (covers extension-less cases
            like ``Dockerfile``).
        extension: The lowercased extension, including the leading dot.

    Returns:
        A language name, or ``None`` if unrecognized.
    """
    if filename.lower() == "dockerfile":
        return "Dockerfile"
    return EXTENSION_LANGUAGE_MAP.get(extension)


def is_hidden(name: str) -> bool:
    """Check whether a file or directory name is conventionally hidden.

    Args:
        name: The file or directory's base name.

    Returns:
        ``True`` if the name starts with a dot (Unix hidden-file convention).
    """
    return name.startswith(".")


@dataclass
class ScannedFile:
    """A single file's collected metadata — never its contents."""

    path: str
    filename: str
    extension: str
    size_bytes: int
    last_modified: datetime
    language: Optional[str]
    is_hidden: bool


@dataclass
class ScanResult:
    """Aggregate output of a full workspace scan."""

    files: list[ScannedFile] = field(default_factory=list)
    total_files: int = 0
    supported_files: int = 0
    ignored_files: int = 0
    folder_count: int = 0
    repository_size_bytes: int = 0
    language_distribution: dict[str, int] = field(default_factory=dict)


def scan_directory(root: Path) -> ScanResult:
    """Recursively walk a repository's local clone, collecting file metadata.

    Ignored directories (``.git``, ``node_modules``, build artifacts,
    etc.) are pruned entirely — never descended into, never counted.
    Every remaining file is classified as supported (recognized
    language) or ignored (unrecognized extension); no file's contents
    are ever read, only filesystem metadata via ``stat()``.

    Args:
        root: The repository's local clone directory.

    Returns:
        A populated :class:`ScanResult`.
    """
    result = ScanResult()

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRECTORY_NAMES]
        result.folder_count += len(dirnames)

        for filename in filenames:
            file_path = Path(dirpath) / filename
            try:
                stat_result = file_path.stat()
            except OSError:
                continue

            relative_path = file_path.relative_to(root).as_posix()
            extension = file_path.suffix.lower()
            language = detect_language(filename, extension)

            scanned = ScannedFile(
                path=relative_path,
                filename=filename,
                extension=extension,
                size_bytes=stat_result.st_size,
                last_modified=datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc),
                language=language,
                is_hidden=is_hidden(filename),
            )
            result.files.append(scanned)
            result.total_files += 1
            result.repository_size_bytes += scanned.size_bytes

            if language:
                result.supported_files += 1
                result.language_distribution[language] = result.language_distribution.get(language, 0) + 1
            else:
                result.ignored_files += 1

    return result


def build_tree(files: list[File]) -> list[TreeNode]:
    """Build a nested folder/file tree from a flat list of file rows.

    Args:
        files: All file rows for a repository (any order).

    Returns:
        The top-level nodes of a nested tree — folders contain their
        children, files are leaves. No file contents are included.
    """
    root: dict[str, dict] = {}

    for db_file in files:
        parts = Path(db_file.path).parts
        cursor = root
        for index, part in enumerate(parts):
            is_leaf = index == len(parts) - 1
            if part not in cursor:
                cursor[part] = {"node": None, "children": {}}
            if is_leaf:
                cursor[part]["node"] = TreeNode(
                    name=part,
                    type="file",
                    path=db_file.path,
                    language=db_file.language,
                    size_bytes=db_file.size_bytes,
                )
            cursor = cursor[part]["children"]

    def _build(level: dict[str, dict], path_prefix: str) -> list[TreeNode]:
        nodes = []
        for name, entry in sorted(level.items()):
            if entry["node"] is not None and not entry["children"]:
                nodes.append(entry["node"])
            else:
                folder_path = f"{path_prefix}/{name}" if path_prefix else name
                nodes.append(
                    TreeNode(
                        name=name,
                        type="folder",
                        path=folder_path,
                        children=_build(entry["children"], folder_path),
                    )
                )
        return nodes

    return _build(root, "")
