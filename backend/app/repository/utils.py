"""Git operations and filesystem helpers for repository management.

Thin wrapper around GitPython — clone only. No pull, no branch checkout,
no file parsing (that's Ingestion's job — CLAUDE.md §6).
"""
from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

from git import GitCommandError, Repo

from app.repository.exceptions import InvalidRepositoryURLError, RepositoryCloneError

_GITHUB_URL_PATTERN = re.compile(r"^https://github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(\.git)?/?$")


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
        Repo.clone_from(github_url, local_path, depth=1)
    except GitCommandError as exc:
        remove_local_clone(local_path)
        raise RepositoryCloneError(f"Failed to clone '{github_url}': {exc}") from exc


def remove_local_clone(local_path: Path) -> None:
    """Remove a repository's local clone directory, if present.

    Args:
        local_path: The directory to remove.
    """
    shutil.rmtree(local_path, ignore_errors=True)
