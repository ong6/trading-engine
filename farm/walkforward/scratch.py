"""Walk-forward scratch ownership, sharing, and orphan reclamation."""
from __future__ import annotations

import fcntl
import os
import shutil
from contextlib import contextmanager
from pathlib import Path

from engine.lib.settings import REPO_ROOT

SCRATCH_ROOT = REPO_ROOT / "scratch"
ACTIVE_LOCK = ".active.lock"
KEEP_MARKER = ".keep"
SHARED_RUN_ENV = "TRADING_ENGINE_WF_SHARED_RUN"


@contextmanager
def hold_directory(path: Path, *, shared: bool = False):
    """Hold a flock proving that ``path`` belongs to a live worker."""
    path.mkdir(parents=True, exist_ok=True)
    fd = os.open(path / ACTIVE_LOCK, os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(fd, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX))
    try:
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


@contextmanager
def exclusive_file_lock(path: Path):
    """Serialize construction of a shared store inside an active directory."""
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def mark_kept(path: Path) -> None:
    """Keep an explicit ``--keep-scratch`` directory out of orphan sweeps."""
    (path / KEEP_MARKER).touch(exist_ok=True)


def directory_bytes(path: Path) -> int:
    """Return allocated file sizes without following links outside ``path``."""
    total = 0
    for root, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(root) / name).is_symlink()]
        for name in files:
            candidate = Path(root) / name
            try:
                total += candidate.lstat().st_size
            except FileNotFoundError:
                pass
    return total


def _open_paths_under(root: Path) -> set[Path]:
    """Read Linux process descriptors once and retain targets below ``root``."""
    prefix = str(root.resolve()) + os.sep
    found: set[Path] = set()
    proc = Path("/proc")
    if not proc.exists():
        return found
    for process in proc.iterdir():
        if not process.name.isdigit():
            continue
        fd_dir = process / "fd"
        try:
            descriptors = list(fd_dir.iterdir())
        except (FileNotFoundError, PermissionError):
            continue
        for descriptor in descriptors:
            try:
                target = os.readlink(descriptor)
            except (FileNotFoundError, PermissionError, OSError):
                continue
            target = target.removesuffix(" (deleted)")
            if target.startswith(prefix):
                found.add(Path(target))
    return found


def _holds_path(directory: Path, open_paths: set[Path]) -> bool:
    prefix = str(directory) + os.sep
    return any(str(path) == str(directory) or str(path).startswith(prefix)
               for path in open_paths)


def _can_lock_exclusively(directory: Path) -> bool:
    lock_path = directory / ACTIVE_LOCK
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    except FileNotFoundError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        fcntl.flock(fd, fcntl.LOCK_UN)
        return True
    finally:
        os.close(fd)


def sweep_orphans(root: Path = SCRATCH_ROOT) -> dict[str, int]:
    """Remove unheld ``wf__*`` directories and report count/bytes reclaimed.

    A live worker is protected either by its advisory directory lock or by any
    open descriptor below the directory. Explicitly kept inspection scratch is
    not an orphan. Symlinks are never followed or removed.
    """
    root = Path(root)
    if not root.exists():
        return {"removed": 0, "bytes": 0, "held": 0, "kept": 0}
    open_paths = _open_paths_under(root)
    stats = {"removed": 0, "bytes": 0, "held": 0, "kept": 0}
    for directory in sorted(root.glob("wf__*")):
        if directory.is_symlink() or not directory.is_dir():
            continue
        if (directory / KEEP_MARKER).exists():
            stats["kept"] += 1
            continue
        if _holds_path(directory, open_paths) or not _can_lock_exclusively(directory):
            stats["held"] += 1
            continue
        size = directory_bytes(directory)
        shutil.rmtree(directory)
        stats["removed"] += 1
        stats["bytes"] += size
    return stats
