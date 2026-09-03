"""Per-request DuckDB connection helpers for the M3 server.

`read_con()` opens read-only; `write_con()` opens read-write. Both go through
the one connection factory (`engine.lib.db.connect`, which honours env
`TRADING_ENGINE_DB`, default `store/market.duckdb` under the repo root) with
`wait_s=0`: when the DB file is held by another process's write lock (the
nightly league run), opening raises `DBBusyError`, which the API maps to
HTTP 503 — we never hang waiting on the lock.

Thin wrappers only (refactor step 2, 2026-09-03): server/main.py and the tests
depend on these names.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from engine.lib import db as engine_db
from engine.lib.db import DBBusyError  # noqa: F401  (re-export; raised below)
from engine.lib.settings import DEFAULT_DB, REPO_ROOT  # noqa: F401


def db_path() -> Path:
    """Resolved DB path — env `TRADING_ENGINE_DB` or the default store path."""
    return DEFAULT_DB


def _connect(read_only: bool) -> duckdb.DuckDBPyConnection:
    try:
        return engine_db.connect(db_path(), read_only=read_only, wait_s=0)
    except Exception as exc:  # duckdb.IOException et al.
        if engine_db.is_lock_error(exc):
            raise DBBusyError(str(exc)) from exc
        raise


def read_con() -> duckdb.DuckDBPyConnection:
    """Open the DB read-only. Raises DBBusyError if the file is write-locked."""
    return _connect(read_only=True)


def write_con() -> duckdb.DuckDBPyConnection:
    """Open the DB read-write. Raises DBBusyError if the write lock is held."""
    return _connect(read_only=False)
