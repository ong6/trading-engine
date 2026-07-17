"""Per-request DuckDB connection helpers for the M3 server.

`read_con()` opens read-only; `write_con()` opens read-write. Both resolve the DB
path from env `TRADING_ENGINE_DB` (default `store/market.duckdb` under the repo
root). When the DB file is held by another process's write lock (the nightly
league run), opening raises `DBBusyError`, which the API maps to HTTP 503 — we
never hang waiting on the lock.
"""
from __future__ import annotations

import os
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "store" / "market.duckdb"

# Substrings DuckDB uses when the on-disk lock is contended / DB opened elsewhere.
_LOCK_MARKERS = ("lock", "already open", "being used", "conflicting lock")


class DBBusyError(RuntimeError):
    """The DB could not be opened because another process holds a lock."""


def db_path() -> Path:
    """Resolved DB path — env `TRADING_ENGINE_DB` or the default store path."""
    env = os.environ.get("TRADING_ENGINE_DB")
    if env:
        p = Path(env)
        return p if p.is_absolute() else (REPO_ROOT / p)
    return DEFAULT_DB


def _connect(read_only: bool) -> duckdb.DuckDBPyConnection:
    path = db_path()
    try:
        return duckdb.connect(str(path), read_only=read_only)
    except Exception as exc:  # duckdb.IOException et al.
        msg = str(exc).lower()
        if any(m in msg for m in _LOCK_MARKERS):
            raise DBBusyError(str(exc)) from exc
        raise


def read_con() -> duckdb.DuckDBPyConnection:
    """Open the DB read-only. Raises DBBusyError if the file is write-locked."""
    return _connect(read_only=True)


def write_con() -> duckdb.DuckDBPyConnection:
    """Open the DB read-write. Raises DBBusyError if the write lock is held."""
    return _connect(read_only=False)
