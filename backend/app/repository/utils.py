"""Git operations and filesystem helpers for repository management.

Thin wrapper around GitPython — clone only. No pull, no branch checkout,
no file parsing (that's Ingestion's job — CLAUDE.md §6).
"""
from __future__ import annotations

import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from git import GitCommandError, Repo

from app.repository.exceptions import InvalidRepositoryURLError, RepositoryCloneError

_GITHUB_URL_PATTERN = re.compile(r"^https://github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(\.git)?/?$")

# Never let a clone block waiting for credentials, and never download LFS
# payloads (a pointer file is enough for us and can be gigabytes otherwise).
_CLONE_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1"}


@dataclass(frozen=True)
class TreeMeasure:
    """Result of measuring a cloned working tree against limits."""

    files: int
    bytes: int
    exceeded: bool


def parse_github_url(url: str) -> tuple[str, str]:
    """Validate a GitHub repository URL and extract its owner/repo segments.

    Args:
        url: The URL supplied by the client.

    Returns:
        A ``(owner, repo)`` tuple.

    Raises:
        InvalidRepositoryURLError: If the URL is not a well-formed
            ``https://github.com/<owner>/<repo>`` URL.
    """
    match = _GITHUB_URL_PATTERN.match(url.strip())
    if not match:
        raise InvalidRepositoryURLError(f"'{url}' is not a valid GitHub repository URL.")
    return match.group("owner"), match.group("repo")


def build_local_path(base_path: Path, repository_id: uuid.UUID) -> Path:
    """Compute the local clone destination for a repository.

    Args:
        base_path: Root storage directory for all cloned repositories.
        repository_id: The repository's own primary key, used as a
            collision-free directory name.

    Returns:
        The path the repository should be cloned into.
    """
    return base_path / str(repository_id)


def local_clone_exists(local_path: Path) -> bool:
    """Check whether a repository has already been cloned to disk.

    Args:
        local_path: The expected clone destination.

    Returns:
        ``True`` if the path exists and contains a ``.git`` directory.
    """
    return local_path.exists() and (local_path / ".git").exists()


def clone_repository(github_url: str, local_path: Path) -> None:
    """Shallow-clone a GitHub repository to a local path.

    Args:
        github_url: The validated source URL.
        local_path: Destination directory.

    Raises:
        RepositoryCloneError: If GitPython fails to clone the repository.
            Any partial clone directory is removed before raising.
    """
    local_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        Repo.clone_from(github_url, local_path, depth=1, env=_CLONE_ENV, multi_options=["--no-tags"])
    except GitCommandError as exc:
        remove_local_clone(local_path)
        raise RepositoryCloneError(f"Failed to clone '{github_url}': {exc}") from exc


def measure_tree(local_path: Path, max_files: Optional[int], max_bytes: Optional[int]) -> TreeMeasure:
    """Count files and bytes in a cloned working tree, stopping early once a limit is crossed.

    The ``.git`` directory is excluded: the limits are about what will be
    parsed and embedded, not about git's own object store. Symlinks are
    not followed, so a malicious link cannot make the walk escape the clone.

    Args:
        local_path: The cloned repository directory.
        max_files: File-count limit, or ``None`` for unlimited.
        max_bytes: Total-size limit in bytes, or ``None`` for unlimited.

    Returns:
        The counts so far and whether any limit was exceeded (the walk stops
        at the first excess, so counts are lower bounds in that case).
    """
    files = total = 0
    for directory, subdirs, names in os.walk(local_path, followlinks=False):
        if ".git" in subdirs:
            subdirs.remove(".git")
        for name in names:
            path = Path(directory) / name
            if path.is_symlink():
                continue
            files += 1
            try:
                total += path.stat().st_size
            except OSError:
                continue
            if (max_files is not None and files > max_files) or (max_bytes is not None and total > max_bytes):
                return TreeMeasure(files=files, bytes=total, exceeded=True)
    return TreeMeasure(files=files, bytes=total, exceeded=False)


def remove_local_clone(local_path: Path) -> None:
    """Remove a repository's local clone directory, if present.

    Args:
        local_path: The directory to remove.
    """
    # ``Path("")`` is ``Path(".")``: a repository row whose ``local_path`` was
    # never filled in would otherwise make this delete the working directory.
    if str(local_path) in ("", "."):
        return
    shutil.rmtree(local_path, ignore_errors=True)
