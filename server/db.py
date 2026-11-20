"""Per-request DuckDB connection helpers for the local paper-trading API.

`read_con()` opens an independent cursor on the last verified readable generation. Only the
background worker verifies publications; requests never wait for it. `pending_verification`
identifies a publication not yet selected. `pending_publication` says whether the primary has changed since the
generation was captured; a generation that is both older than its dataset's budget and
possibly behind the primary is served and flagged stale.
An absent or unreadable verified generation refuses (503). `write_con()` alone opens the primary, waiting a
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
from threading import Lock
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
    verified_snapshot_file,
)

_DATA_SOURCE_STATE: ContextVar[dict | None] = ContextVar("api_data_source_state", default=None)
# Staleness budgets: a generation older than its dataset's budget is still served, but the
# response says it is stale. During US market hours a changed
# primary is republished at most once every three hours (publish-on-change),
# so evidence there lags its last write by at most 3 hours plus one publication (about 15
# minutes); 3.5 hours covers it. Responses still flag pending_publication.
GENERAL_GENERATION_MAX_AGE = timedelta(hours=24)
DATASET_GENERATION_MAX_AGE = {
    "board": GENERAL_GENERATION_MAX_AGE,
    "evidence": timedelta(minutes=210),
}
_DATASET_CLASS: ContextVar[str] = ContextVar("api_dataset_class", default="board")
# A publication holds a read-only capture handle while it copies the primary: 50-130 s for
# the 12.7 GB store under write traffic in the rehearsal. API writes wait that out.
API_WRITE_WAIT_S = float(os.environ.get("TRADING_ENGINE_API_WRITE_WAIT_S", "180"))
_WRITE_RETRY_S = 0.25


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

    def __init__(self, connection: duckdb.DuckDBPyConnection, generation, release):
        self._connection = connection
        self._generation = generation
        self._release = release
        self._closed = False

    def __getattr__(self, name: str):
        return getattr(self._connection, name)

    @property
    def generation_info(self):
        """The pinned generation's manifest record (``SnapshotInfo``)."""
        return self._generation.pin.info

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._connection.close()
        finally:
            self._release(self._generation)

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


class DBNotReadyError(DBBusyError):
    """No fully verified readable generation is available to this request."""


class _VerifiedGeneration:
    def __init__(self, database: Path, pin: SnapshotPin, connection):
        self.database = database
        self.pin = pin
        self.connection = connection
        self.users = 1  # selector ownership, plus one for each request or worker lease
        self.readable = True

    def close(self):
        try:
            self.connection.close()
        finally:
            self.pin.close()


class _GenerationReader:
    """Atomically select verified connections without holding locks during I/O."""

    def __init__(self):
        self._lock = Lock()
        self._refresh_lock = Lock()
        self._current: _VerifiedGeneration | None = None
        self._pending_id: str | None = None
        self._observed_id: str | None = None

    def _published_id(self) -> str | None:
        try:
            target = Path(os.readlink(db_path().parent / "snapshots" / "market-latest.duckdb"))
        except OSError:
            return None
        return target.stem if not target.is_absolute() and len(target.parts) == 1 else None

    def _observe_publication(self) -> None:
        published = self._published_id()
        with self._lock:
            current = self._current
            served = current.pin.info.generation_id if current else None
            self._observed_id = published
            self._pending_id = published if published != served else None

    def _retain(self, *, require_readable: bool = True) -> _VerifiedGeneration:
        with self._lock:
            current = self._current
            if (current is None or current.database != db_path()
                    or (require_readable and not current.readable)):
                raise DBNotReadyError("database not ready: no verified readable generation")
            current.users += 1
            return current

    def _release(self, generation: _VerifiedGeneration) -> None:
        with self._lock:
            generation.users -= 1
            close = generation.users == 0
        if close:
            generation.close()

    def _mark_readable(self, generation, readable: bool) -> None:
        with self._lock:
            generation.readable = readable

    def read(self):
        self._observe_publication()  # a symlink read only; no manifest, hash or store lock
        generation = self._retain()
        try:
            connection = generation.connection.cursor()
        except Exception as exc:
            self._mark_readable(generation, False)
            self._release(generation)
            raise DBNotReadyError("database not ready: verified generation is unreadable") from exc
        result = _PinnedConnection(connection, generation, self._release)
        try:
            state = _DATA_SOURCE_STATE.get()
            if state is not None:
                served = {**generation_state(generation.pin),
                          **self.pending_state(generation.pin.info.generation_id)}
                state.update(source="snapshot", snapshot_as_of=served["as_of"],
                             generation_id=served["generation_id"], generation=served)
            return result
        except BaseException:
            result.close()
            raise

    def pending_state(self, served_id: str) -> dict:
        with self._lock:
            pending = self._observed_id if self._observed_id != served_id else None
            return {"pending_verification": pending is not None,
                    "pending_generation_id": pending}

    def readiness(self) -> dict:
        with self._lock:
            current = self._current
            ok = current is not None and current.database == db_path() and current.readable
            info = current.pin.info if ok else None
            return {"ok": ok, "status": "ready" if ok else "not ready",
                    "generation_id": info.generation_id if info else None,
                    "as_of": info.as_of.isoformat() if info else None,
                    "pending_verification": self._pending_id is not None,
                    "pending_generation_id": self._pending_id}

    def refresh(self) -> bool:
        """Worker-only verification, readability check and atomic generation switch."""
        with self._refresh_lock:
            self._observe_publication()
            try:
                current = self._retain(require_readable=False)
            except DBNotReadyError:
                current = None
            if current is not None:
                try:
                    valid = verified_snapshot_file(current.pin.info.path) is not None
                    with current.connection.cursor() as check:
                        valid = valid and check.execute("SELECT 1").fetchone() == (1,)
                    self._mark_readable(current, valid)
                    if valid and self._published_id() == current.pin.info.generation_id:
                        return True
                except Exception:
                    self._mark_readable(current, False)
                finally:
                    self._release(current)
            # Only this background path acquires a pin, hashes bytes or opens DuckDB.
            pin = pin_latest_generation(db_path())
            try:
                connection = engine_db.connect(pin.info.path, read_only=True, wait_s=0)
            except BaseException:
                pin.close()
                raise
            candidate = _VerifiedGeneration(db_path(), pin, connection)
            try:
                if connection.execute("SELECT 1").fetchone() != (1,):
                    raise GenerationError("verified generation is unreadable")
                published = self._published_id()
                with self._lock:
                    previous = self._current
                    self._current = candidate
                    self._observed_id = published
                    self._pending_id = published if published != pin.info.generation_id else None
            except BaseException:
                candidate.close()
                raise
            if previous is not None:
                self._release(previous)
            return True

    def close(self) -> None:
        with self._lock:
            current, self._current = self._current, None
            self._pending_id = None
            self._observed_id = None
        if current is not None:
            self._release(current)


_generation_reader = _GenerationReader()


def refresh_generation() -> bool:
    """Worker entrypoint; leave the previous generation selected on verification failure."""
    return _generation_reader.refresh()


def readiness() -> dict:
    """In-memory result of the background verification and readability checks."""
    return _generation_reader.readiness()


def close_generation_reader() -> None:
    """Release selector ownership; active request leases retain their own lifetimes."""
    _generation_reader.close()


def read_con() -> duckdb.DuckDBPyConnection:
    """Serve the last verified generation with an independent request cursor."""
    return _generation_reader.read()


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
