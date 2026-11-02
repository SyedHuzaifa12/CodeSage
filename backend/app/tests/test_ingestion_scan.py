"""Unit tests for the noise-filtering repository scanner (``ingestion/utils.py``).

Pure filesystem tests (``tmp_path``) — no database, no network. Exercises
the pipeline-optimization pass's broadened exclusion strategy: built-in
directory/filename/suffix rules, .gitignore-awareness, the configurable
size cap, and the inspectable excluded-file breakdown.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import get_settings
from app.ingestion.utils import scan_directory


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """Ensure each test sees freshly-read env vars for ``IngestionSettings``."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _write(root: Path, relative_path: str, content: str = "x") -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestBuiltInExclusionRules:
    def test_ignored_directories_are_pruned_entirely(self, tmp_path: Path):
        _write(tmp_path, "src/app.py", "print('hi')")
        _write(tmp_path, "node_modules/some_pkg/index.js", "module.exports = {}")
        _write(tmp_path, ".git/HEAD", "ref: refs/heads/main")
        _write(tmp_path, "__pycache__/app.cpython-311.pyc", "binary")

        result = scan_directory(tmp_path)

        paths = {f.path for f in result.files}
        assert paths == {"src/app.py"}
        # Pruned directories are never descended into, so their files
        # are not even counted as "excluded" — they're simply never seen.
        assert "node_modules/some_pkg/index.js" not in paths

    def test_known_lockfiles_are_excluded_by_filename(self, tmp_path: Path):
        _write(tmp_path, "package-lock.json", "{}" * 10)
        _write(tmp_path, "src/index.js", "console.log(1)")

        result = scan_directory(tmp_path)

        paths = {f.path for f in result.files}
        assert "package-lock.json" not in paths
        assert "src/index.js" in paths
        assert result.excluded_by_reason.get("filename_rule") == 1
        assert any(s["path"] == "package-lock.json" and s["reason"] == "filename_rule" for s in result.excluded_samples)

    def test_minified_and_sourcemap_suffixes_are_excluded(self, tmp_path: Path):
        _write(tmp_path, "dist/bundle.min.js", "a" * 100)
        _write(tmp_path, "dist/bundle.js.map", "{}")
        _write(tmp_path, "src/app.js", "const x = 1;")

        result = scan_directory(tmp_path)

        paths = {f.path for f in result.files}
        # dist/ itself is also an ignored directory, so these never even
        # reach the suffix check — confirms directory pruning wins first.
        assert paths == {"src/app.js"}

    def test_suffix_exclusion_applies_outside_ignored_directories(self, tmp_path: Path):
        _write(tmp_path, "src/bundle.min.js", "a" * 100)
        _write(tmp_path, "src/app.js", "const x = 1;")

        result = scan_directory(tmp_path)

        paths = {f.path for f in result.files}
        assert paths == {"src/app.js"}
        assert result.excluded_by_reason.get("suffix_rule") == 1


class TestGitignoreAwareness:
    def test_gitignore_patterns_are_respected_by_default(self, tmp_path: Path):
        _write(tmp_path, ".gitignore", "*.local.json\nscratch/\n")
        _write(tmp_path, "config.local.json", "{}")
        _write(tmp_path, "scratch/notes.txt", "wip")
        _write(tmp_path, "src/app.py", "print(1)")

        result = scan_directory(tmp_path)

        paths = {f.path for f in result.files}
        assert "config.local.json" not in paths
        assert "scratch/notes.txt" not in paths
        assert "src/app.py" in paths
        assert result.excluded_by_reason.get("gitignore", 0) >= 1

    def test_gitignore_can_be_disabled(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        _write(tmp_path, ".gitignore", "*.local.json\n")
        _write(tmp_path, "config.local.json", "{}")
        monkeypatch.setenv("INGESTION_RESPECT_GITIGNORE", "false")
        get_settings.cache_clear()

        result = scan_directory(tmp_path)

        paths = {f.path for f in result.files}
        assert "config.local.json" in paths

    def test_missing_gitignore_is_not_an_error(self, tmp_path: Path):
        _write(tmp_path, "src/app.py", "print(1)")

        result = scan_directory(tmp_path)

        assert {f.path for f in result.files} == {"src/app.py"}
        assert result.excluded_count == 0


class TestSizeCap:
    def test_oversized_files_are_excluded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("INGESTION_MAX_FILE_SIZE_BYTES", "100")
        get_settings.cache_clear()
        _write(tmp_path, "data/huge.json", "x" * 1000)
        _write(tmp_path, "src/app.py", "print(1)")

        result = scan_directory(tmp_path)

        paths = {f.path for f in result.files}
        assert "data/huge.json" not in paths
        assert "src/app.py" in paths
        assert result.excluded_by_reason.get("max_file_size") == 1


class TestConfigurableExtraExclusions:
    def test_extra_ignored_dirs_and_filenames_are_configurable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("INGESTION_EXTRA_IGNORED_DIRS", "generated")
        monkeypatch.setenv("INGESTION_EXTRA_IGNORED_FILENAMES", "secrets.local.yaml")
        get_settings.cache_clear()
        _write(tmp_path, "generated/output.py", "# generated")
        _write(tmp_path, "secrets.local.yaml", "key: value")
        _write(tmp_path, "src/app.py", "print(1)")

        result = scan_directory(tmp_path)

        paths = {f.path for f in result.files}
        assert paths == {"src/app.py"}


class TestPreservedFiles:
    def test_source_tests_docs_and_config_are_kept(self, tmp_path: Path):
        _write(tmp_path, "src/app.py", "print(1)")
        _write(tmp_path, "tests/test_app.py", "def test_x(): pass")
        _write(tmp_path, "docs/README.md", "# docs")
        _write(tmp_path, "migrations/0001_init.sql", "CREATE TABLE x();")
        _write(tmp_path, "pyproject.toml", "[tool.x]")

        result = scan_directory(tmp_path)

        paths = {f.path for f in result.files}
        assert paths == {
            "src/app.py", "tests/test_app.py", "docs/README.md",
            "migrations/0001_init.sql", "pyproject.toml",
        }
        assert result.excluded_count == 0


class TestExcludedSamplesCap:
    def test_excluded_samples_are_capped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("INGESTION_MAX_FILE_SIZE_BYTES", "1")
        get_settings.cache_clear()
        for i in range(250):
            _write(tmp_path, f"data/file_{i}.bin", "xx")

        result = scan_directory(tmp_path)

        assert result.excluded_count == 250
        assert len(result.excluded_samples) <= 200
