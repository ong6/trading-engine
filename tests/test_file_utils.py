"""Tests for race-resistant operational artifact reads."""

import os
from contextlib import AbstractContextManager
from pathlib import Path
from typing import BinaryIO

import pytest

from server import file_utils


class _MutatingReader(AbstractContextManager):
    def __init__(self, source: BinaryIO, mutate):
        self.source = source
        self.mutate = mutate
        self.mutated = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.source.close()

    def fileno(self):
        return self.source.fileno()

    def read(self, size=-1):
        payload = self.source.read(size)
        if not self.mutated:
            self.mutate()
            self.mutated = True
        return payload

    def seek(self, offset, whence=0):
        return self.source.seek(offset, whence)


def _mutating_open(monkeypatch, mutate):
    original = file_utils.open_regular

    def open_then_mutate(path: Path, *, label: str = "file"):
        return _MutatingReader(original(path, label=label), mutate)

    monkeypatch.setattr(file_utils, "open_regular", open_then_mutate)


def test_bounded_file_reader_accepts_exact_limit_and_rejects_one_byte_more(tmp_path):
    path = tmp_path / "artifact.txt"
    path.write_bytes(b"x" * 16)
    assert file_utils.read_bytes(path, max_bytes=16, label="artifact") == b"x" * 16

    path.write_bytes(b"x" * 17)
    with pytest.raises(ValueError, match="artifact file exceeds 16 bytes"):
        file_utils.read_bytes(path, max_bytes=16, label="artifact")


@pytest.mark.parametrize("limit", [-1, 1.5, True])
def test_bounded_file_reader_rejects_invalid_size_limit(tmp_path, limit):
    path = tmp_path / "artifact.txt"
    path.write_text("local")

    with pytest.raises(ValueError, match="max_bytes must be a non-negative integer"):
        file_utils.read_bytes(path, max_bytes=limit, label="artifact")


@pytest.mark.parametrize("kind", ["symlink", "dangling-symlink", "directory", "fifo"])
def test_bounded_file_reader_rejects_non_regular_path_without_blocking(tmp_path, kind):
    path = tmp_path / "artifact.txt"
    if kind == "symlink":
        target = tmp_path / "target.txt"
        target.write_text("external")
        path.symlink_to(target)
    elif kind == "dangling-symlink":
        path.symlink_to(tmp_path / "missing.txt")
    elif kind == "directory":
        path.mkdir()
    else:
        os.mkfifo(path)

    with pytest.raises(ValueError, match="artifact path must be a regular file"):
        file_utils.read_text(path, label="artifact")


def test_bounded_file_reader_allows_regular_file_below_symlinked_parent(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    (target / "artifact.txt").write_text("local")
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)

    assert file_utils.read_text(alias / "artifact.txt", label="artifact") == "local"


def test_strict_bounded_file_reader_rejects_symlinked_parent(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    (target / "artifact.txt").write_text("local")
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)

    with pytest.raises(ValueError, match="artifact parent path must not contain symlinks"):
        file_utils.read_text(
            alias / "artifact.txt",
            label="artifact",
            allow_symlinked_parents=False,
        )


def test_strict_bounded_file_reader_rejects_parent_replacement(tmp_path, monkeypatch):
    parent = tmp_path / "parent"
    parent.mkdir()
    path = parent / "artifact.txt"
    path.write_text("original")
    displaced = tmp_path / "displaced"
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    (replacement / "artifact.txt").write_text("replacement")
    original = file_utils._read_bounded
    replaced = False

    def read_then_replace(source, max_bytes):
        nonlocal replaced
        payload = original(source, max_bytes)
        if not replaced:
            replaced = True
            parent.rename(displaced)
            replacement.rename(parent)
        return payload

    monkeypatch.setattr(file_utils, "_read_bounded", read_then_replace)

    with pytest.raises(ValueError, match="artifact path changed while reading"):
        file_utils.read_text(path, label="artifact", allow_symlinked_parents=False)


def test_strict_bounded_file_reader_classifies_parent_removal_as_path_change(
    tmp_path, monkeypatch
):
    parent = tmp_path / "parent"
    parent.mkdir()
    path = parent / "artifact.txt"
    path.write_text("original")
    displaced = tmp_path / "displaced"
    original = file_utils._read_bounded
    removed = False

    def read_then_remove(source, max_bytes):
        nonlocal removed
        payload = original(source, max_bytes)
        if not removed:
            removed = True
            parent.rename(displaced)
        return payload

    monkeypatch.setattr(file_utils, "_read_bounded", read_then_remove)

    with pytest.raises(file_utils.PathChangedError, match="artifact path changed while reading"):
        file_utils.read_text(path, label="artifact", allow_symlinked_parents=False)


def test_bounded_file_reader_rejects_in_place_mutation_during_read(tmp_path, monkeypatch):
    path = tmp_path / "artifact.txt"
    path.write_text("original")
    _mutating_open(monkeypatch, lambda: path.write_text("modified"))

    with pytest.raises(ValueError, match="artifact path changed while reading"):
        file_utils.read_text(path, label="artifact")


def test_bounded_file_reader_rejects_path_replacement_during_read(tmp_path, monkeypatch):
    path = tmp_path / "artifact.txt"
    path.write_text("original")
    replacement = tmp_path / "replacement.txt"
    replacement.write_text("replacement")
    _mutating_open(monkeypatch, lambda: replacement.replace(path))

    with pytest.raises(ValueError, match="artifact path changed while reading"):
        file_utils.read_text(path, label="artifact")


def test_bounded_file_reader_rejects_path_removal_during_read(tmp_path, monkeypatch):
    path = tmp_path / "artifact.txt"
    path.write_text("original")
    _mutating_open(monkeypatch, path.unlink)

    with pytest.raises(ValueError, match="artifact path changed while reading"):
        file_utils.read_text(path, label="artifact")
