"""Race-resistant reads for local operational artifacts."""

from __future__ import annotations

import os
import stat
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import BinaryIO

MAX_OPERATIONAL_FILE_BYTES = 1_048_576


class PathChangedError(ValueError):
    """The visible path stopped naming the securely opened file."""


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _stable_metadata(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


@contextmanager
def _open_parent_no_follow(path: Path, *, label: str):
    """Retain an absolute parent chain without following any component symlink."""
    absolute = Path(os.path.abspath(path))
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise ValueError(f"secure {label} parent traversal is unavailable")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | directory | nofollow
    stack = ExitStack()
    try:
        current = os.open(absolute.anchor, flags)
        stack.callback(os.close, current)
        identities = [_identity(os.fstat(current))]
        for part in absolute.parts[1:-1]:
            current = os.open(part, flags, dir_fd=current)
            stack.callback(os.close, current)
            identities.append(_identity(os.fstat(current)))
    except FileNotFoundError:
        stack.close()
        raise
    except OSError as exc:
        stack.close()
        raise ValueError(f"{label} parent path must not contain symlinks") from exc
    try:
        yield current, absolute.name, tuple(identities)
    finally:
        stack.close()


def verify_visible_regular(path: Path, source: BinaryIO, *, label: str = "file") -> os.stat_result:
    """Require the visible final path to name the opened regular file."""
    opened = os.fstat(source.fileno())
    try:
        visible = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise PathChangedError(f"{label} path changed while reading") from exc
    if not stat.S_ISREG(visible.st_mode) or _identity(opened) != _identity(visible):
        raise PathChangedError(f"{label} path changed while reading")
    return visible


def open_regular(path: Path, *, label: str = "file") -> BinaryIO:
    """Open a final path without following links or blocking on special files."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow and path.is_symlink():
        raise ValueError(f"{label} path must be a regular file, not a symlink")
    try:
        descriptor = os.open(path, flags | nofollow)
    except OSError as exc:
        if path.is_symlink():
            raise ValueError(f"{label} path must be a regular file, not a symlink") from exc
        raise
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError(f"{label} path must be a regular file")
        if not nofollow:
            try:
                visible = path.stat(follow_symlinks=False)
            except OSError as exc:
                raise PathChangedError(f"{label} path changed while opening") from exc
            if not stat.S_ISREG(visible.st_mode) or _identity(opened) != _identity(visible):
                raise PathChangedError(f"{label} path changed while opening")
        handle = os.fdopen(descriptor, "rb")
        descriptor = -1
        return handle
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _read_bounded(source: BinaryIO, max_bytes: int) -> tuple[bytes, bytes]:
    payload = source.read(max_bytes + 1)
    source.seek(0)
    return payload, source.read(max_bytes + 1)


def _read_bytes_no_follow(path: Path, *, max_bytes: int, label: str) -> bytes:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise ValueError(f"secure {label} opening is unavailable")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | nofollow
    )
    with _open_parent_no_follow(path, label=label) as (parent_fd, leaf, parent_chain):
        try:
            descriptor = os.open(leaf, flags, dir_fd=parent_fd)
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise ValueError(f"{label} path must be a regular file, not a symlink") from exc
        try:
            with os.fdopen(descriptor, "rb") as source:
                descriptor = -1
                before = os.fstat(source.fileno())
                if not stat.S_ISREG(before.st_mode):
                    raise ValueError(f"{label} path must be a regular file")
                payload, confirmed = _read_bounded(source, max_bytes)
                after = os.fstat(source.fileno())
                try:
                    anchored = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
                except OSError as exc:
                    raise PathChangedError(f"{label} path changed while reading") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        try:
            with _open_parent_no_follow(path, label=label) as (
                visible_parent_fd,
                visible_leaf,
                visible_chain,
            ):
                visible = os.stat(
                    visible_leaf, dir_fd=visible_parent_fd, follow_symlinks=False
                )
        except (OSError, ValueError) as exc:
            raise PathChangedError(f"{label} path changed while reading") from exc
    if (
        payload != confirmed
        or parent_chain != visible_chain
        or not stat.S_ISREG(anchored.st_mode)
        or not stat.S_ISREG(visible.st_mode)
        or _stable_metadata(before) != _stable_metadata(after)
        or _stable_metadata(after) != _stable_metadata(anchored)
        or _stable_metadata(anchored) != _stable_metadata(visible)
    ):
        raise PathChangedError(f"{label} path changed while reading")
    return payload


def read_bytes(
    path: Path,
    *,
    max_bytes: int = MAX_OPERATIONAL_FILE_BYTES,
    label: str = "file",
    allow_symlinked_parents: bool = True,
) -> bytes:
    """Read one stable regular file with a strict request-time size ceiling."""
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 0:
        raise ValueError("max_bytes must be a non-negative integer")
    if allow_symlinked_parents:
        with open_regular(path, label=label) as source:
            before = os.fstat(source.fileno())
            payload, confirmed = _read_bounded(source, max_bytes)
            after = os.fstat(source.fileno())
            visible = verify_visible_regular(path, source, label=label)
            if (
                payload != confirmed
                or _stable_metadata(before) != _stable_metadata(after)
                or _identity(after) != _identity(visible)
            ):
                raise PathChangedError(f"{label} path changed while reading")
    else:
        payload = _read_bytes_no_follow(path, max_bytes=max_bytes, label=label)
    if len(payload) > max_bytes:
        raise ValueError(f"{label} file exceeds {max_bytes} bytes")
    return payload


def read_text(
    path: Path,
    *,
    max_bytes: int = MAX_OPERATIONAL_FILE_BYTES,
    label: str = "file",
    allow_symlinked_parents: bool = True,
) -> str:
    """Read one bounded UTF-8 operational artifact."""
    return read_bytes(
        path,
        max_bytes=max_bytes,
        label=label,
        allow_symlinked_parents=allow_symlinked_parents,
    ).decode("utf-8")
