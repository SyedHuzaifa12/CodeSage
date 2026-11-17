"""Tests for the clone helper (``repository/utils.py``): the hard time limit, stall detection, process cleanup,
and GitHub's pre-download size lookup.

Background: the first hosted deploy showed a repository stuck in "cloning" with no end. The old clone had no time limit,
the guest size cap was only checked after the whole download, and the indexer runs one job at a time, so a single slow
or enormous clone also blocked every repository queued behind it.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from app.repository import utils
from app.repository.exceptions import RepositoryCloneError
from app.repository.utils import clone_repository, fetch_remote_size_kb

GIT_AVAILABLE = subprocess.run(["git", "--version"], capture_output=True).returncode == 0


@pytest.fixture
def local_repo(tmp_path: Path) -> Path:
    """A real, tiny git repository to clone from (no network)."""
    source = tmp_path / "source"
    source.mkdir()
    run = lambda *args: subprocess.run(["git", *args], cwd=source, check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    (source / "app.py").write_text("print('hi')\n", encoding="utf-8")
    run("add", ".")
    run("commit", "-q", "-m", "init")
    return source


@pytest.mark.skipif(not GIT_AVAILABLE, reason="git not installed")
class TestRealClone:
    def test_a_normal_clone_works(self, local_repo, tmp_path):
        destination = tmp_path / "clone"
        clone_repository(local_repo.as_uri(), destination, timeout_seconds=60)
        assert (destination / "app.py").read_text(encoding="utf-8").startswith("print")
        assert (destination / ".git").exists()

    def test_a_missing_repository_fails_fast_with_git_s_own_message_and_leaves_no_directory(self, tmp_path):
        destination = tmp_path / "clone"
        with pytest.raises(RepositoryCloneError, match="Failed to clone"):
            clone_repository((tmp_path / "does-not-exist").as_uri(), destination, timeout_seconds=60)
        assert not destination.exists()


class _FakeProcess:
    """Stands in for a git process so the timeout path is deterministic."""

    pid = 4242

    def __init__(self, *, hang: bool = False, returncode: int = 0, stderr: str = ""):
        self.hang, self.returncode, self._stderr, self.killed, self.communicate_calls = hang, returncode, stderr, False, []

    def communicate(self, timeout=None):
        self.communicate_calls.append(timeout)
        if self.hang and not self.killed:
            raise subprocess.TimeoutExpired("git", timeout)
        return "", self._stderr

    def kill(self):
        self.killed = True


@pytest.fixture
def fake_git(monkeypatch):
    holder = {}

    def popen(command, **kwargs):
        holder["command"], holder["kwargs"] = command, kwargs
        return holder["process"]

    monkeypatch.setattr(utils.subprocess, "Popen", popen)
    monkeypatch.setattr(utils, "_kill_process_tree", lambda process: setattr(process, "killed", True))
    return holder


class TestTimeoutsAndCleanup:
    def test_a_clone_that_runs_out_of_time_is_killed_cleaned_up_and_reported(self, fake_git, tmp_path):
        destination = tmp_path / "clone"
        destination.mkdir()  # the partial download
        (destination / "partial.pack").write_text("x")
        process = fake_git["process"] = _FakeProcess(hang=True)

        with pytest.raises(RepositoryCloneError) as raised:
            clone_repository("https://github.com/o/huge", destination, timeout_seconds=7)

        assert process.killed and not destination.exists()
        assert "stopped after 7 seconds" in str(raised.value) and "smaller repository" in str(raised.value)
        assert len(process.communicate_calls) == 2  # waited with the limit, then reaped the killed process

    def test_the_limit_is_handed_to_the_wait(self, fake_git, tmp_path):
        process = fake_git["process"] = _FakeProcess()
        clone_repository("https://github.com/o/r", tmp_path / "c", timeout_seconds=123)
        assert process.communicate_calls == [123]

    def test_git_is_told_to_abort_a_stalled_transfer_not_just_wait_for_the_hard_limit(self, fake_git, tmp_path):
        fake_git["process"] = _FakeProcess()
        clone_repository("https://github.com/o/r", tmp_path / "c")
        command = " ".join(fake_git["command"])
        assert "http.lowSpeedLimit=" in command and "http.lowSpeedTime=60" in command

    def test_it_is_still_a_shallow_tagless_clone_that_never_prompts_for_credentials(self, fake_git, tmp_path):
        fake_git["process"] = _FakeProcess()
        clone_repository("https://github.com/o/r", tmp_path / "c")
        assert ["--depth", "1"] == fake_git["command"][fake_git["command"].index("--depth"):][:2]
        assert "--no-tags" in fake_git["command"] and fake_git["command"][-3] == "--"  # the URL cannot be read as an option
        env = fake_git["kwargs"]["env"]
        assert env["GIT_TERMINAL_PROMPT"] == "0" and env["GIT_LFS_SKIP_SMUDGE"] == "1"

    @pytest.mark.skipif(not hasattr(os, "killpg"), reason="process groups are POSIX-only")
    def test_git_runs_in_its_own_process_group_so_its_helper_processes_can_be_killed_too(self, fake_git, tmp_path):
        fake_git["process"] = _FakeProcess()
        clone_repository("https://github.com/o/r", tmp_path / "c")
        assert fake_git["kwargs"]["start_new_session"] is True

    def test_a_failing_git_reports_the_tail_of_its_error_and_removes_the_directory(self, fake_git, tmp_path):
        destination = tmp_path / "clone"
        destination.mkdir()
        fake_git["process"] = _FakeProcess(returncode=128, stderr="fatal: repository not found\n")
        with pytest.raises(RepositoryCloneError, match="repository not found"):
            clone_repository("https://github.com/o/missing", destination)
        assert not destination.exists()

    @pytest.mark.skipif(not hasattr(os, "killpg"), reason="process groups are POSIX-only")
    def test_the_kill_really_takes_down_the_process_and_its_children(self):
        # Real processes, no fakes: a parent that spawns a sleeping child, started the same way the clone is.
        parent = subprocess.Popen(
            [sys.executable, "-c", "import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); time.sleep(60)"],
            start_new_session=True,
        )
        time.sleep(0.5)
        utils._kill_process_tree(parent)
        assert parent.wait(timeout=5) != 0  # killed, not finished


class TestRemoteSizeLookup:
    def _client(self, handler):
        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_reports_the_size_github_gives(self):
        seen = []
        client = self._client(lambda request: (seen.append(request), httpx.Response(200, json={"size": 15432}))[1])
        assert fetch_remote_size_kb("https://github.com/expressjs/express", client=client) == 15432
        assert str(seen[0].url) == "https://api.github.com/repos/expressjs/express"
        assert seen[0].headers["user-agent"]  # GitHub rejects requests without one

    @pytest.mark.parametrize(
        "response",
        [
            httpx.Response(404, json={"message": "Not Found"}),
            httpx.Response(403, json={"message": "API rate limit exceeded"}),
            httpx.Response(500),
            httpx.Response(200, text="<html>not json</html>"),
            httpx.Response(200, json={"name": "no size field"}),
            httpx.Response(200, json={"size": "big"}),
        ],
    )
    def test_anything_unexpected_means_unknown_never_an_error(self, response):
        assert fetch_remote_size_kb("https://github.com/o/r", client=self._client(lambda request: response)) is None

    def test_a_network_failure_means_unknown(self):
        def boom(request):
            raise httpx.ConnectTimeout("slow")

        assert fetch_remote_size_kb("https://github.com/o/r", client=self._client(boom)) is None

    def test_a_url_that_is_not_a_github_repository_means_unknown(self):
        assert fetch_remote_size_kb("https://example.com/o/r", client=self._client(lambda r: pytest.fail("no request"))) is None
