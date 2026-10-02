"""Per-request DuckDB connection helpers for the local paper-trading API.

`read_con()` opens read-only; `write_con()` opens read-write. Both go through
the one connection factory (`engine.lib.db.connect`, which honours env
`TRADING_ENGINE_DB`, default `store/market.duckdb` under the repo root) with
`wait_s=0`: when the DB file is held by another process's write lock, read-only
requests may use the latest valid immutable snapshot while writes still raise
`DBBusyError`. Evidence-validation callers additionally require a snapshot
published after the live database's last write.

Thin wrappers only (refactor step 2, 2026-09-03): server/main.py and the tests
depend on these names.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator

import duckdb

from engine.lib import db as engine_db
from engine.lib.db import DBBusyError
from engine.lib.settings import DEFAULT_DB
from engine.lib.snapshots import latest_snapshot

_DATA_SOURCE_STATE: ContextVar[dict[str, str | None] | None] = ContextVar(
    "api_data_source_state", default=None
)
_EVIDENCE_SNAPSHOT_REQUIRED: ContextVar[bool] = ContextVar(
    "evidence_snapshot_required", default=False
)


def db_path() -> Path:
    """Resolved DB path — env `TRADING_ENGINE_DB` or the default store path."""
    return DEFAULT_DB


def _connect(read_only: bool) -> duckdb.DuckDBPyConnection:
    try:
        return engine_db.connect(db_path(), read_only=read_only, wait_s=0)
    except Exception as exc:  # duckdb.IOException et al.
        different_configuration = (
            "same database file with a different configuration" in str(exc).lower()
        )
        if engine_db.is_lock_error(exc) or different_configuration:
            raise DBBusyError(str(exc)) from exc
        raise


def read_con() -> duckdb.DuckDBPyConnection:
    """Open the primary read-only, falling back only on lock contention."""
    try:
        return _connect(read_only=True)
    except DBBusyError as primary_error:
        snapshot = latest_snapshot(
            db_path(), newer_than_database=_EVIDENCE_SNAPSHOT_REQUIRED.get()
        )
        if snapshot is None:
            raise
        try:
            connection = engine_db.connect(snapshot.path, read_only=True, wait_s=0)
        except Exception as snapshot_error:
            raise primary_error from snapshot_error
        state = _DATA_SOURCE_STATE.get()
        if state is not None:
            state.update(
                source="snapshot",
                snapshot_as_of=snapshot.as_of.isoformat(),
            )
        return connection


def write_con() -> duckdb.DuckDBPyConnection:
    """Open the DB read-write. Raises DBBusyError if the write lock is held."""
    return _connect(read_only=False)


@contextmanager
def response_data_source() -> Iterator[dict[str, str | None]]:
    """Track the source selected by a request for response-header middleware."""
    state = {"source": "primary", "snapshot_as_of": None}
    token = _DATA_SOURCE_STATE.set(state)
    try:
        yield state
    finally:
        _DATA_SOURCE_STATE.reset(token)


@contextmanager
def require_fresh_evidence_snapshot() -> Iterator[None]:
    """Allow snapshot fallback only if publication followed the last DB write."""
    token = _EVIDENCE_SNAPSHOT_REQUIRED.set(True)
    try:
        yield
    finally:
        _EVIDENCE_SNAPSHOT_REQUIRED.reset(token)
