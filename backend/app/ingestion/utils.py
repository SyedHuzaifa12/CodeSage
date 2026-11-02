"""File-system scanning and tree-building helpers.

Metadata only — no file is ever opened for its *contents* (only
``stat()`` and, for ``.gitignore`` itself, a small text read). Tree-sitter
parsing and symbol extraction are explicitly out of scope for this module.

Noise-filtering strategy (pipeline-optimization pass): a repository scan
excludes three independent categories, each recorded with its own reason
so the exclusion is inspectable rather than silent:

1. **Structural/tooling directories** — VCS metadata, dependency
   directories, build output, IDE/tooling caches. Pruned by name before
   ``os.walk`` ever descends into them (cheapest possible skip).
2. **Known noise files** — lockfiles, minified/bundled output, source
   maps, common binary/media/archive extensions — excluded by filename
   or suffix regardless of directory.
3. **The repository's own ``.gitignore``** — a strong, repo-specific
   signal: whatever a project's own maintainers chose to keep out of
   version control is, by construction, not meant to represent "the
   codebase" either. Parsed with ``pathspec`` (the same gitignore-match
   semantics ``git`` itself uses) and respected by default
   (``IngestionSettings.ingestion_respect_gitignore``).

A fourth, size-based cutoff (``IngestionSettings.ingestion_max_file_size_bytes``)
catches anything not covered by name/suffix/gitignore — e.g. a committed
database dump or a large uncompressed asset.

All of the above is configurable via ``IngestionSettings`` (env vars) so
exclusion rules never require a code change for a project-specific case.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pathspec

from app.core.config import get_settings
from app.ingestion.schemas import TreeNode
from app.models.file import File

# Version control, dependency, build-output, and editor/tooling
# directories: never source, never worth descending into. Pruned by name
# during the walk, so neither their contents nor their own sub-trees are
# ever visited (the dominant cost saving for dependency-heavy repos like
# a Node project with a multi-hundred-MB ``node_modules``).
IGNORED_DIRECTORY_NAMES = frozenset(
    {
        # VCS
        ".git", ".hg", ".svn",
        # Dependency directories (multi-language)
        "node_modules", "bower_components", "vendor", "vendor-bin",
        ".venv", "venv", "env", ".tox", "site-packages", "__pypackages__",
        "Pods", ".gradle", ".m2", "packages",
        # Build / compiled output
        "dist", "build", "out", "target", "bin", "obj", ".next", ".nuxt",
        ".turbo", ".svelte-kit", "cdk.out", ".serverless",
        # Caches / tooling state
        "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
        ".idea", ".vscode", ".vs", ".DS_Store",
        # Coverage / test artifacts
        "coverage", "htmlcov", ".nyc_output",
        # Terraform/infra state caches
        ".terraform",
    }
)

# Exact filenames with zero semantic value for code understanding, and a
# real reliability risk if they reach a chunker/embedder unbounded
# (lockfiles in particular can be tens of MB of flat JSON/YAML with no
# meaningful top-level structure for Tree-sitter either). This is the
# single source of truth for "known lockfile/manifest noise" — Knowledge's
# embedding stage reuses this list rather than keeping its own, narrower
# copy (see ``knowledge/service.py::_is_excluded_from_knowledge_indexing``).
IGNORED_FILENAMES = frozenset(
    {
        "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml",
        "composer.lock", "Gemfile.lock", "poetry.lock", "Pipfile.lock",
        "go.sum", "Cargo.lock", "mix.lock", "flake.lock",
        ".DS_Store", "Thumbs.db", "desktop.ini",
    }
)

# Suffixes identifying generated/minified/compiled artifacts and common
# binary/media/archive formats — none of these represent hand-authored
# source worth parsing, chunking, or embedding.
IGNORED_SUFFIXES = (
    ".min.js", ".min.css", ".map",
    ".pyc", ".pyo", ".class", ".o", ".obj", ".so", ".dll", ".dylib", ".exe",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
    ".mp3", ".mp4", ".mov", ".avi", ".wav", ".flac",
    ".zip", ".tar", ".gz", ".tgz", ".rar", ".7z", ".whl", ".jar", ".war",
    ".pdf", ".woff", ".woff2", ".ttf", ".eot",
    ".db", ".sqlite", ".sqlite3",
)

_GITIGNORE_FILENAME = ".gitignore"

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
    # Noise filtered out entirely (never becomes a `File` row), broken
    # down by why — inspectable rather than a silent drop. Keys:
    # "directory_rule", "filename_rule", "suffix_rule", "gitignore",
    # "max_file_size".
    excluded_count: int = 0
    excluded_by_reason: dict[str, int] = field(default_factory=dict)
    # A capped sample (never the full list, to keep the workspace row
    # small) of what was excluded and why, for API/log inspectability.
    excluded_samples: list[dict] = field(default_factory=list)


_MAX_EXCLUDED_SAMPLES = 200


def _load_gitignore_spec(root: Path) -> Optional["pathspec.PathSpec"]:
    """Parse a repository's own ``.gitignore`` into a matchable pathspec.

    Only the root ``.gitignore`` is read (the common case for the
    repositories this platform targets); nested per-directory
    ``.gitignore`` files are not merged in V1 — documented as a known,
    low-cost limitation rather than implementing full git ignore-stack
    resolution.

    Args:
        root: The repository's local clone directory.

    Returns:
        A compiled pathspec, or ``None`` if no ``.gitignore`` exists or
        it could not be read/parsed.
    """
    gitignore_path = root / _GITIGNORE_FILENAME
    if not gitignore_path.is_file():
        return None
    try:
        lines = gitignore_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    try:
        return pathspec.PathSpec.from_lines("gitignore", lines)
    except KeyError:
        # Older ``pathspec`` releases only register "gitwildmatch".
        return pathspec.PathSpec.from_lines("gitwildmatch", lines)


def _exclusion_reason(
    *,
    filename: str,
    extension: str,
    relative_path: str,
    size_bytes: int,
    ignored_dir_names: frozenset,
    ignored_filenames: frozenset,
    ignored_suffixes: tuple,
    gitignore_spec: Optional["pathspec.PathSpec"],
    max_file_size_bytes: int,
) -> Optional[str]:
    """Classify a file as noise, or ``None`` if it should be kept.

    Checked cheapest-first: name/suffix lookups before the gitignore
    match, since the vast majority of exclusions are caught by the
    built-in lists alone.

    Returns:
        One of ``"filename_rule"``, ``"suffix_rule"``, ``"gitignore"``,
        ``"max_file_size"``, or ``None`` if the file is kept.
    """
    if filename in ignored_filenames:
        return "filename_rule"
    if filename.endswith(ignored_suffixes):
        return "suffix_rule"
    if gitignore_spec is not None and gitignore_spec.match_file(relative_path):
        return "gitignore"
    if size_bytes > max_file_size_bytes:
        return "max_file_size"
    return None


def scan_directory(root: Path) -> ScanResult:
    """Recursively walk a repository's local clone, collecting file metadata.

    Noise is filtered in two stages: ignored *directories* (VCS,
    dependency, build-output, tooling) are pruned entirely — never
    descended into, never even stat()'d — and remaining *files* are
    checked against the filename/suffix/.gitignore/size rules in
    :func:`_exclusion_reason`. Every kept file is further classified as
    supported (recognized language) or ignored (unrecognized extension,
    but not noise — e.g. a ``.txt`` README asset). No file's contents
    are ever read (except the repository's own ``.gitignore``, as plain
    text, to build the match spec).

    Args:
        root: The repository's local clone directory.

    Returns:
        A populated :class:`ScanResult`.
    """
    ingestion_settings = get_settings().ingestion
    ignored_dir_names = IGNORED_DIRECTORY_NAMES | frozenset(ingestion_settings.extra_ignored_dirs_list)
    ignored_filenames = IGNORED_FILENAMES | frozenset(ingestion_settings.extra_ignored_filenames_list)
    ignored_suffixes = IGNORED_SUFFIXES + tuple(ingestion_settings.extra_ignored_suffixes_list)
    max_file_size_bytes = ingestion_settings.ingestion_max_file_size_bytes

    gitignore_spec = _load_gitignore_spec(root) if ingestion_settings.ingestion_respect_gitignore else None

    result = ScanResult()

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ignored_dir_names]
        result.folder_count += len(dirnames)

        for filename in filenames:
            file_path = Path(dirpath) / filename
            try:
                stat_result = file_path.stat()
            except OSError:
                continue

            relative_path = file_path.relative_to(root).as_posix()
            extension = file_path.suffix.lower()

            reason = _exclusion_reason(
                filename=filename,
                extension=extension,
                relative_path=relative_path,
                size_bytes=stat_result.st_size,
                ignored_dir_names=ignored_dir_names,
                ignored_filenames=ignored_filenames,
                ignored_suffixes=ignored_suffixes,
                gitignore_spec=gitignore_spec,
                max_file_size_bytes=max_file_size_bytes,
            )
            if reason is not None:
                result.excluded_count += 1
                result.excluded_by_reason[reason] = result.excluded_by_reason.get(reason, 0) + 1
                if len(result.excluded_samples) < _MAX_EXCLUDED_SAMPLES:
                    result.excluded_samples.append({"path": relative_path, "reason": reason})
                continue

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
