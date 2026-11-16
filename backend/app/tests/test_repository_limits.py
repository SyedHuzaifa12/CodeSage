"""Unit tests for clone-size measurement and the empty-path deletion guard (ADR-027)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.repository.utils import measure_tree, remove_local_clone


def populate(root: Path, files: int, size: int = 10) -> None:
    for index in range(files):
        (root / f"f{index}.txt").write_bytes(b"x" * size)


def test_measure_counts_files_and_bytes(tmp_path: Path) -> None:
    populate(tmp_path, files=4, size=25)
    measure = measure_tree(tmp_path, max_files=None, max_bytes=None)
    assert (measure.files, measure.bytes, measure.exceeded) == (4, 100, False)


def test_git_directory_is_not_counted(tmp_path: Path) -> None:
    populate(tmp_path, files=2)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "huge-pack").write_bytes(b"x" * 10_000)
    measure = measure_tree(tmp_path, max_files=5, max_bytes=1000)
    assert measure.files == 2
    assert not measure.exceeded


def test_exceeding_file_count_is_detected_early(tmp_path: Path) -> None:
    populate(tmp_path, files=20)
    measure = measure_tree(tmp_path, max_files=5, max_bytes=None)
    assert measure.exceeded
    assert measure.files == 6  # stops at the first file past the limit instead of walking everything


def test_exceeding_size_is_detected(tmp_path: Path) -> None:
    populate(tmp_path, files=3, size=500)
    assert measure_tree(tmp_path, max_files=None, max_bytes=1000).exceeded


def test_exactly_at_the_limit_is_allowed(tmp_path: Path) -> None:
    populate(tmp_path, files=3, size=10)
    assert not measure_tree(tmp_path, max_files=3, max_bytes=30).exceeded


def test_nested_directories_are_walked(tmp_path: Path) -> None:
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "deep.py").write_bytes(b"x" * 7)
    assert measure_tree(tmp_path, None, None).files == 1


@pytest.mark.skipif(os.name == "nt", reason="creating symlinks needs elevated rights on Windows")
def test_symlinks_are_not_followed(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_bytes(b"x" * 5000)
    clone = tmp_path / "clone"
    clone.mkdir()
    (clone / "link").symlink_to(outside, target_is_directory=True)
    assert measure_tree(clone, None, None).files == 0


def test_removing_an_empty_path_never_touches_the_working_directory(tmp_path: Path, monkeypatch) -> None:
    sentinel = tmp_path / "keep.txt"
    sentinel.write_text("do not delete")
    monkeypatch.chdir(tmp_path)
    remove_local_clone(Path(""))
    remove_local_clone(Path("."))
    assert sentinel.exists()


def test_removing_a_real_clone_directory_works(tmp_path: Path) -> None:
    clone = tmp_path / "clone"
    clone.mkdir()
    populate(clone, files=2)
    remove_local_clone(clone)
    assert not clone.exists()
