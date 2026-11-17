"""Git operations and filesystem helpers for repository management.

A thin wrapper around the ``git`` command — clone only. No pull, no branch checkout,
no file parsing (that's Ingestion's job — CLAUDE.md §6).
"""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

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


DEFAULT_CLONE_TIMEOUT_SECONDS = 600.0

# A transfer slower than this for this long is treated as stalled and aborted by git itself, so a dead
# connection fails in a minute instead of hanging the (single-job) indexer until the hard timeout.
_LOW_SPEED_LIMIT_BYTES_PER_SECOND = 10_000
_LOW_SPEED_TIME_SECONDS = 60


def _kill_process_tree(process: subprocess.Popen) -> None:
    """Kill git and the helper processes it spawned (``git-remote-https``), not just the parent."""
    try:
        if hasattr(os, "killpg"):
            os.killpg(process.pid, signal.SIGKILL)  # the clone runs in its own process group (see below)
        else:
            process.kill()  # Windows (development only)
    except (ProcessLookupError, PermissionError, OSError):
        process.kill()


def clone_repository(github_url: str, local_path: Path, timeout_seconds: float = DEFAULT_CLONE_TIMEOUT_SECONDS) -> None:
    """Shallow-clone a GitHub repository to a local path, with a hard time limit.

    Without a limit one stalled or enormous download hangs forever: the indexer runs one job at a time,
    keeps renewing its lease while it waits, and so every later repository queues behind it.

    Args:
        github_url: The validated source URL.
        local_path: Destination directory.
        timeout_seconds: Hard limit for the whole clone; git is killed when it passes.

    Raises:
        RepositoryCloneError: If git fails, stalls, or runs out of time. Any partial clone
            directory is removed before raising.
    """
    local_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "git",
        "-c", f"http.lowSpeedLimit={_LOW_SPEED_LIMIT_BYTES_PER_SECOND}",
        "-c", f"http.lowSpeedTime={_LOW_SPEED_TIME_SECONDS}",
        "clone", "--depth", "1", "--no-tags", "--quiet", "--", github_url, str(local_path),
    ]
    popen_options = {"start_new_session": True} if hasattr(os, "killpg") else {}
    process = subprocess.Popen(
        command, env={**os.environ, **_CLONE_ENV}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **popen_options
    )
    try:
        _, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        _kill_process_tree(process)
        process.communicate()
        remove_local_clone(local_path)
        raise RepositoryCloneError(
            f"Cloning '{github_url}' was stopped after {int(timeout_seconds)} seconds: the repository is too large "
            "or GitHub was too slow. Try a smaller repository."
        ) from None
    if process.returncode != 0:
        remove_local_clone(local_path)
        raise RepositoryCloneError(f"Failed to clone '{github_url}': {(stderr or '').strip()[-400:]}")


# GitHub's reported repository size covers the whole history; a shallow clone is typically a fraction of it.
GITHUB_API_TIMEOUT_SECONDS = 8.0


def fetch_remote_size_kb(github_url: str, *, client: Optional[httpx.Client] = None) -> Optional[int]:
    """Ask GitHub how big a repository is, without downloading it.

    Lets a guest's oversized repository be refused in a second instead of after a long download. Best effort:
    any failure (rate limit, private repository, network) returns ``None`` and the clone proceeds normally.

    Args:
        github_url: A validated ``https://github.com/<owner>/<repo>`` URL.
        client: Optional HTTP client (tests inject a mock transport).

    Returns:
        The repository's size in kilobytes, or ``None`` if it could not be determined.
    """
    try:
        owner, repo = parse_github_url(github_url)
        owns_client = client is None
        client = client or httpx.Client(timeout=GITHUB_API_TIMEOUT_SECONDS)
        try:
            response = client.get(
                f"https://api.github.com/repos/{owner}/{repo}",
                headers={"Accept": "application/vnd.github+json", "User-Agent": "codesage"},
            )
        finally:
            if owns_client:
                client.close()
        if response.status_code != 200:
            return None
        size = response.json().get("size")
        return int(size) if isinstance(size, (int, float)) else None
    except Exception:  # noqa: BLE001 -- purely an optimisation; never let it block an import
        return None


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
