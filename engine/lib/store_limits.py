"""Store resource limits: a free-space reserve and per-connection DuckDB limits.

Free space. Store writes, backups and snapshot copies refuse before they fill the store
filesystem.

Every writer of the live store, the backup bundle and the snapshot publisher calls
``require_free_space`` before it starts. The check is one ``statvfs``: free bytes on the
filesystem holding the path must cover the bytes the operation is about to add plus a
reserve that is never spent (``TRADING_ENGINE_MIN_FREE_GIB``, default and minimum 70 GiB, so the other
producers, DuckDB's write-ahead log and the logs keep room). A refusal raises
``DiskSpaceError`` naming the operation, the path, the free bytes and what it needed, before
any byte is written; nothing here deletes or prunes.

``store_path_guarded`` limits the writer check to this checkout's ``store/`` tree, so test and
scratch databases elsewhere are never refused by the host's free space.

DuckDB limits. DuckDB's defaults are every core and 80% of RAM per connection, so the API, the
producers and a research job each assume the whole host. ``duckdb_limits`` gives readers (API
requests, checks) 4 threads / 4GB and writers (producers) 8 / 16GB, overridden by
``TRADING_ENGINE_DUCKDB_THREADS`` / ``TRADING_ENGINE_DUCKDB_MEMORY``; heavy jobs that set their
own values on their connection keep them.
"""

from __future__ import annotations

import math
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from engine.lib.settings import REPO_ROOT

MIN_FREE_ENV = "TRADING_ENGINE_MIN_FREE_GIB"
DEFAULT_MIN_FREE_GIB = 70.0
GIB = 1024**3
STORE_ROOT = REPO_ROOT / "store"

DiskUsage = Callable[[Path], Any]


class DiskSpaceError(OSError):
    """An operation would leave the store filesystem below its reserve."""


def reserve_bytes() -> int:
    """The reserve that must stay free, read at call time (``TRADING_ENGINE_MIN_FREE_GIB``)."""
    raw = os.environ.get(MIN_FREE_ENV)
    try:
        gib = DEFAULT_MIN_FREE_GIB if raw in (None, "") else float(raw)
    except ValueError as exc:
        raise DiskSpaceError(f"{MIN_FREE_ENV}={raw!r} is not a number of GiB") from exc
    if not math.isfinite(gib) or gib < DEFAULT_MIN_FREE_GIB:
        raise DiskSpaceError(
            f"{MIN_FREE_ENV}={raw!r} must be finite and at least {DEFAULT_MIN_FREE_GIB:g} GiB; "
            "the store reserve cannot be lowered"
        )
    return int(gib * GIB)


def _existing(path: Path) -> Path:
    """The nearest existing ancestor: a file not created yet lives on its parent's filesystem."""
    path = Path(path).absolute()
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def require_free_space(
    path: str | Path, *, purpose: str, need_bytes: int = 0,
    disk_usage: DiskUsage = shutil.disk_usage,
) -> dict:
    """Raise ``DiskSpaceError`` unless ``need_bytes`` plus the reserve are free at ``path``."""
    reserve = reserve_bytes()
    need = max(0, int(need_bytes))
    anchor = _existing(Path(path))
    free = int(disk_usage(anchor).free)
    report = {"path": str(anchor), "free_bytes": free, "need_bytes": need,
              "reserve_bytes": reserve}
    if free < need + reserve:
        raise DiskSpaceError(
            f"refusing {purpose}: {free / GIB:.1f} GiB free on the filesystem of {anchor}, "
            f"needs {need / GIB:.1f} GiB plus the {reserve / GIB:.1f} GiB reserve "
            f"({MIN_FREE_ENV})"
        )
    return report


def store_path_guarded(path: str | Path) -> bool:
    """Whether ``path`` is inside this checkout's live ``store/`` tree.

    Both sides are resolved: the home directory can be a symbolic link to the data volume,
    so a ``~/trading-engine/store`` path and the checkout's own path must compare equal.
    """
    try:
        Path(os.path.realpath(path)).relative_to(os.path.realpath(STORE_ROOT))
    except ValueError:
        return False
    return True


def file_bytes(path: str | Path) -> int:
    """Size of a database file and its write-ahead log; 0 for a missing file."""
    total = 0
    for candidate in (Path(path), Path(f"{path}.wal")):
        try:
            total += candidate.stat().st_size
        except FileNotFoundError:
            continue
    return total


DUCKDB_THREADS_ENV = "TRADING_ENGINE_DUCKDB_THREADS"
DUCKDB_MEMORY_ENV = "TRADING_ENGINE_DUCKDB_MEMORY"
DUCKDB_READER_LIMITS = (4, "4GB")
DUCKDB_WRITER_LIMITS = (8, "16GB")


def duckdb_limits(read_only: bool) -> tuple[int, str]:
    """(threads, memory_limit) for a new store connection, read at call time."""
    threads, memory = DUCKDB_READER_LIMITS if read_only else DUCKDB_WRITER_LIMITS
    raw_threads = os.environ.get(DUCKDB_THREADS_ENV, "")
    raw_memory = os.environ.get(DUCKDB_MEMORY_ENV, "")
    if raw_threads:
        threads = int(raw_threads)
        if threads < 1:
            raise ValueError(f"{DUCKDB_THREADS_ENV} must be at least 1")
    if raw_memory:
        memory = raw_memory.strip()
        if not memory[:1].isdigit() or "'" in memory:
            raise ValueError(f"{DUCKDB_MEMORY_ENV} must look like 8GB")
    return threads, memory
