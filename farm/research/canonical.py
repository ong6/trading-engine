"""Canonical JSON and content identities used by the research control plane."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any


def canonical_bytes(value: Any, *, newline: bool = False) -> bytes:
    """Encode finite JSON with one stable byte representation."""
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("value is not canonical JSON") from exc
    return encoded + (b"\n" if newline else b"")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_digest(paths: list[tuple[str, Path]]) -> str:
    digest = hashlib.sha256()
    for name, path in sorted(paths):
        encoded = name.encode()
        content = path.read_bytes()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


@lru_cache(maxsize=None)
def distribution_sha256(name: str) -> str:
    """Hash every installed file of one distribution, including native extensions."""
    distribution = importlib.metadata.distribution(name)
    paths = []
    root = Path(distribution.locate_file("")).resolve()
    for item in distribution.files or ():
        path = Path(distribution.locate_file(item)).resolve()
        if (path.is_file() and path.is_relative_to(root)
                and "__pycache__" not in path.parts):
            paths.append((path.relative_to(root).as_posix(), path))
    if not paths:
        raise ValueError(f"runtime distribution has no files: {name}")
    return _tree_digest(paths)


@lru_cache(maxsize=1)
def python_runtime_sha256() -> str:
    """Bind interpreter, stdlib/native modules, and its dynamically linked libraries."""
    prefix = Path(sys.base_prefix).resolve()
    paths = [
        (path.relative_to(prefix).as_posix(), path)
        for path in prefix.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    ]
    try:
        output = subprocess.run(
            ["ldd", str(Path(sys.executable).resolve())],
            check=True, capture_output=True, text=True, timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("cannot resolve interpreter native libraries") from exc
    for line in output.splitlines():
        candidate = line.split("=>", 1)[-1].strip().split(" ", 1)[0]
        path = Path(candidate)
        if path.is_absolute() and path.is_file():
            paths.append((f"linked/{path.as_posix()}", path.resolve()))
    return _tree_digest(paths)


def fsync_tree(root: str | Path) -> None:
    """Flush files and directories before publishing an immutable object."""
    base = Path(root)
    for path in sorted(base.rglob("*"), reverse=True):
        if path.is_file():
            with path.open("rb") as handle:
                os.fsync(handle.fileno())
        elif path.is_dir():
            descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    descriptor = os.open(base, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
