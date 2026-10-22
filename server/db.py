"""Per-request DuckDB connection helpers for the local paper-trading API.

`read_con()` pins and opens the newest immutable generation; it never refuses because
publication is behind. `pending_publication` says whether the primary has changed since the
generation was captured; a generation that is both older than its dataset's budget and
possibly behind the primary is served and flagged stale.
Only "no generation at all" refuses (503). `write_con()` alone opens the primary, waiting a
bounded time for a short lock (a publication's capture copy) instead of failing at once.

Thin wrappers only (refactor step 2, 2026-09-03): server/main.py and the tests
depend on these names.
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

import duckdb

from engine.lib import db as engine_db
from engine.lib.db import DBBusyError
from engine.lib.settings import DEFAULT_DB
from engine.lib.snapshots import (
    GenerationError,
    SnapshotPin,
    pin_latest_generation,
    source_storage_identity,
)

_DATA_SOURCE_STATE: ContextVar[dict | None] = ContextVar("api_data_source_state", default=None)
# Staleness budgets: a generation older than its dataset's budget is still served, but the
# response says it is stale and /health reports "degraded". Evidence is published after
# every evidence writer and at least every PUBLISH_ON_CHANGE interval (ops/jobs.toml).
GENERAL_GENERATION_MAX_AGE = timedelta(hours=24)
DATASET_GENERATION_MAX_AGE = {
    "board": GENERAL_GENERATION_MAX_AGE,
    "evidence": timedelta(minutes=45),
}
_DATASET_CLASS: ContextVar[str] = ContextVar("api_dataset_class", default="board")
API_WRITE_WAIT_S = float(os.environ.get("TRADING_ENGINE_API_WRITE_WAIT_S", "45"))
_WRITE_RETRY_S = 0.5


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


def generation_state(pin: SnapshotPin, *, dataset: str | None = None) -> dict:
    """Describe a pinned generation: age, staleness against its budget, pending writes."""
    budget = DATASET_GENERATION_MAX_AGE[dataset or _DATASET_CLASS.get()]
    age = datetime.now(timezone.utc) - pin.info.as_of
    try:
        pending = pin.info.source_storage_identity != source_storage_identity(db_path())
    except OSError:
        pending = None
    return {
        "generation_id": pin.info.generation_id,
        "as_of": pin.info.as_of.isoformat(),
        "age_seconds": max(0, int(age.total_seconds())),
        "budget_seconds": int(budget.total_seconds()),
        # Past its budget AND possibly behind the primary: a generation captured from the
        # primary's current bytes is current however old it is (a quiet weekend).
        "stale": age > budget and pending is not False,
        "pending_publication": pending,
    }


def read_con() -> duckdb.DuckDBPyConnection:
    """Pin and open the newest immutable generation; never open the primary."""
    try:
        pin = pin_latest_generation(db_path())
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
            served = generation_state(pin)
            state.update(
                source="snapshot", snapshot_as_of=served["as_of"],
                generation_id=served["generation_id"], generation=served,
            )
        return _PinnedConnection(connection, pin)
    except BaseException:
        connection.close()
        pin.close()
        raise


def served_generation() -> dict | None:
    """The generation the current request read from, as recorded by `read_con()`."""
    state = _DATA_SOURCE_STATE.get()
    return None if state is None else state.get("generation")


def write_con() -> duckdb.DuckDBPyConnection:
    """Open the primary read-write, waiting up to API_WRITE_WAIT_S for a short lock."""
    deadline = time.monotonic() + API_WRITE_WAIT_S
    while True:
        try:
            return _connect(read_only=False)
        except DBBusyError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(_WRITE_RETRY_S)


@contextmanager
def response_data_source() -> Iterator[dict]:
    """Track the source selected by a request for response-header middleware."""
    state = {
        "source": "generation", "snapshot_as_of": None, "generation_id": None,
        "generation": None,
    }
    token = _DATA_SOURCE_STATE.set(state)
    try:
        yield state
    finally:
        _DATA_SOURCE_STATE.reset(token)


@contextmanager
def require_fresh_evidence_snapshot() -> Iterator[None]:
    """Judge the served generation against the evidence budget (it is never refused)."""
    dataset_token = _DATASET_CLASS.set("evidence")
    try:
        yield
    finally:
        _DATASET_CLASS.reset(dataset_token)
