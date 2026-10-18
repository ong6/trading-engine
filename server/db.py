"""Per-request DuckDB connection helpers for the local paper-trading API.

`read_con()` pins and opens only the current immutable generation. `write_con()`
alone opens the primary through the one connection factory. Evidence-validation
callers additionally require a generation published after the primary's last
committed write marker.

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
from engine.lib.snapshots import GenerationError, SnapshotPin, pin_latest_generation

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


class _PinnedConnection:
    """DuckDB connection proxy that holds its generation pin until close."""

    def __init__(self, connection: duckdb.DuckDBPyConnection, pin: SnapshotPin):
        self._connection = connection
        self._pin = pin

    def __getattr__(self, name: str):
        return getattr(self._connection, name)

    def close(self) -> None:
        try:
            self._connection.close()
        finally:
            self._pin.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def read_con() -> duckdb.DuckDBPyConnection:
    """Pin and open the current immutable generation; never open the primary."""
    try:
        pin = pin_latest_generation(
            db_path(), newer_than_database=_EVIDENCE_SNAPSHOT_REQUIRED.get(),
        )
    except GenerationError as exc:
        raise DBBusyError(str(exc)) from exc
    try:
        connection = engine_db.connect(pin.info.path, read_only=True, wait_s=0)
    except Exception:
        pin.close()
        raise
    try:
        state = _DATA_SOURCE_STATE.get()
        if state is not None:
            state.update(
                source="snapshot",
                snapshot_as_of=pin.info.as_of.isoformat(),
            )
        return _PinnedConnection(connection, pin)
    except BaseException:
        connection.close()
        pin.close()
        raise


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
